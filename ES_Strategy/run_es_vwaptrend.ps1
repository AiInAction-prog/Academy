# =====================================================================
#  ES/MES VWAP Trend-Pullback  -  Topstep 50K combine, COMBINE-SAFE sizing
#  PRIMARY ES STRATEGY (best edge found on ES)
#
#  WHY THIS CONFIG: a full IS/OOS walk-forward of every strategy on a STITCHED
#  ES dataset (M26+U26, ~52 trading days -- the broker feed caps ~60d, so a true
#  90d isn't available) found NQ-tuned defaults LOSE on ES. After re-tuning to ES
#  scale AND skipping the choppy 08:30-09:00 open, vwap_trend is the best, most
#  robust edge -- MANY configs (not one) are positive in both IS and OOS:
#     ADX_MIN 30, target 2.5R, band stop (VWAP +/- 4pt), cooldown 120s, skip-30
#     IS +$5,107 (PF 1.39, n=74) | OOS +$8,640 (PF 2.22, n=38)  [1 ES contract]
#     full-window 1 MES: ~$42/day median, maxDD ~$206 (skip-30 cut DD sharply)
#  Edge: only trades WITH the trend (ADX >= 30), buying pullbacks to session
#  VWAP in an uptrend / selling rallies in a downtrend; 2.5R target, stop beyond VWAP.
#
#  HONEST EXPECTATION: still NOT $800-1,200/day inside a $2,000 trailing drawdown
#  on the FULL-window read. Sized below to ~$208/day median at 5 MES (modeled
#  maxDD ~$1,028, big buffer). The held-out OOS stretch was richer (hinted at
#  $1,000+/day at 14-19 MES) but it's an 11-day sample -- do NOT bank on it.
#  Live drawdown is almost always worse than backtest; start conservative.
#  Bump to 7 MES (~$291/day, DD ~$1,439) only after a clean live week.
#
#  Run (paper first!):
#     powershell -ExecutionPolicy Bypass -File ES_Strategy\run_es_vwaptrend.ps1
# =====================================================================

$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$VenvPy = Join-Path $RepoRoot '.venv\Scripts\python.exe'
$Py = if (Test-Path $VenvPy) { $VenvPy } else { 'python' }

# --- Account + instrument (MES for granular sizing under the tight DD) ---
if (-not $env:ACCOUNT_ID) {
    Write-Host 'ERROR: set ACCOUNT_ID, e.g. $env:ACCOUNT_ID=''YOUR_MES_ACCOUNT''' -ForegroundColor Red
    exit 1
}
$env:SYMBOL_ROOT = 'MES'
$env:CONTRACT_ID = ''                # blank -> auto-resolve MES front month
$env:TSX_ENV     = 'live'

# --- Execution: START IN PAPER. Flip to 'false' only after a clean paper week.
if (-not $env:PAPER_MODE) { $env:PAPER_MODE = 'true' }

# --- Strategy: ES-tuned VWAP trend-pullback ---
#  RE-TUNED 2026-06-23 (was R2.5/skip30 and traded ~0/day -- no VWAP pullback all
#  day). A 55-day walk-forward (IS/OOS, net of $0.37 commission) winner:
#     adxmin30, target 1.5R, band stop (VWAP +/- 4pt), skip0 ->
#     full 55d: 64 trades, 50% win, PF 1.70, net +$702 / 1 MES, maxDD $207
#     IS net +$302 (n37) | OOS net +$372 (n23, PF 2.19)  [robust_edge=True]
#  Two changes vs the old config drove it: target 2.5R->1.5R (more, smaller wins)
#  and skip0 (the 08:30 open hour was the SINGLE best hour, +$211; old skip30
#  threw it away).
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
$env:SKIP_FIRST_MINUTES          = '0'     # trade the open hour (validated best hour)
$env:ALLOW_LONG                  = 'true'
$env:ALLOW_SHORT                 = 'true'

# --- Session (CME RTH = 08:30-15:00 CT) ---
$env:SESSION_TZ               = 'America/Chicago'
$env:SESSION_OPEN            = '08:30'
$env:SESSION_CLOSE           = '15:00'
$env:FLATTEN_BEFORE_CLOSE_MIN = '5'

# --- Risk caps: re-tuned config has 1-MES maxDD ~$207 over 55d, so 5 MES =>
#     ~$1,035 modeled DD, comfortably under the $1,800 trailing. ~5 MES =>
#     ~$95/day backtest. Bump to 7 (~$1,449 DD, ~$133/day) only after a clean week.
$env:MAX_CONTRACTS_PER_TRADE = '5'
$env:DAILY_LOSS_LIMIT        = '900'
$env:TRAILING_DRAWDOWN       = '1800'
$env:MAX_TRADES_PER_DAY      = '10'
$env:MAX_CONSECUTIVE_LOSSES  = '4'
$env:DAILY_PROFIT_TARGET     = '0'
# Absolute account-balance floor: halts + flattens if live balance reaches this,
# ACROSS restarts. Set to ~ (combine high-water mark - $1.8k). UPDATE per run.
if (-not $env:MIN_ACCOUNT_EQUITY) { $env:MIN_ACCOUNT_EQUITY = '48200' }

# --- Isolated logs + journal ---
$env:LOG_DIR      = 'logs/es_vwaptrend'
$env:JOURNAL_FILE = 'data/es_vwaptrend.csv'
$env:LOG_LEVEL    = 'INFO'

Write-Host "=== MES VWAP Trend-Pullback (re-tuned R1.5/skip0) | acct $($env:ACCOUNT_ID) | MES x$($env:MAX_CONTRACTS_PER_TRADE) ===" -ForegroundColor Cyan
Write-Host "Python: $Py" -ForegroundColor DarkGray
Write-Host "PAPER_MODE=$($env:PAPER_MODE)" -ForegroundColor Yellow

& $Py run_bot.py --non-interactive
