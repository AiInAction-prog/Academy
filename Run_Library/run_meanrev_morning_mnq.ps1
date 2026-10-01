# =====================================================================
#  Morning MNQ Mean-Reversion  (single script for an 8am-3pm ET day)
#  Combine account: 24271301  (50KTC-V2-187845-61461235)
#
#  WHAT THIS IS: the S1 mean-reversion engine (the only strategy with a
#  positive edge over the full ~90-day NQ sample: PF ~1.11) run on MNQ
#  micros so the drawdown fits a $2,000 combine, sized to multiple
#  contracts to target ~$800-1,100 on a good morning.
#
#  WHY MNQ + multi-contract: on full NQ the 90-day max drawdown was
#  ~$5,505 - fatal to a $2k combine. MNQ is $2/pt vs NQ's $20/pt (1/10th
#  the risk), so N MNQ contracts give NQ-like dollars at a fraction of the
#  blow-up risk, while the $900 daily-loss halt + 3-consecutive-loss cap
#  bound a bad day.
#
#  WHY MORNING-ONLY: the edge is concentrated in the cash-open hours.
#  S1 90-day P&L by hour (CT): 08:00 +$1,490, 09:00 +$2,630, 10:00 +$850,
#  11:00 +$1,635, then 12:00 -$1,095 / 13:00 -$1,030 (afternoon bleeds).
#  So new entries are gated to 08:30-11:30 CT (= 09:30 ET cash open to
#  12:30 ET) via ENTRY_END; the bot then only manages/flattens and is flat
#  by the 14:00 CT (15:00 ET) close.
#
#  TIME MAP (your 8am-3pm ET window, in America/Chicago):
#    08:00 ET (07:00 CT)  launch -> idles until the open (skips premarket bleed)
#    09:30 ET (08:30 CT)  SESSION_OPEN -> entries begin
#    12:30 ET (11:30 CT)  ENTRY_END    -> no NEW entries (manage only)
#    15:00 ET (14:00 CT)  SESSION_CLOSE-> auto-flat 5 min before
#
#  Run it (from anywhere):
#     powershell -ExecutionPolicy Bypass -File Run_Library\run_meanrev_morning_mnq.ps1
# =====================================================================

$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$VenvPy = Join-Path $RepoRoot '.venv\Scripts\python.exe'
$Py = if (Test-Path $VenvPy) { $VenvPy } else { 'python' }

# --- Account + instrument ---
if (-not $env:ACCOUNT_ID) {
    Write-Host 'ERROR: set ACCOUNT_ID, e.g. $env:ACCOUNT_ID=''YOUR_MNQ_ACCOUNT''' -ForegroundColor Red
    exit 1
}
$env:SYMBOL_ROOT = 'MNQ'             # micros: $2/pt (1/10th of NQ)
$env:CONTRACT_ID = ''                # blank -> auto-resolve MNQ front month
$env:TSX_ENV     = 'live'

# --- Execution: live sim orders on the combine, unattended ---
$env:PAPER_MODE  = 'false'

# --- Strategy: S1 mean reversion (z2.0, lb80, ATR stops, TREND FILTER OFF) ---
#  RE-TUNED 2026-06-25 after two live trend-fade losing days (06-24 -$175,
#  06-25 -$431). On a freshly-fetched 55d window the OLD fixed-15pt-stop config
#  had gone OUT-OF-SAMPLE NEGATIVE (OOS -$1,205, PF 0.69, worst day -$715, a
#  15-trade losing streak): a fixed 15pt stop is far too tight when trend-day ATR
#  runs 30-55, so every fade is stopped inside the noise. Diagnosis showed an ATR
#  *ceiling* wouldn't help (06-25's bleed was LOW-ATR ~13), and a trend-slope
#  filter stayed OOS-negative at every threshold. The fix that worked: VOLATILITY-
#  SCALED (ATR) stops. Walk-forward winner (net of $0.37 commission):
#     z2.0 lb80, stop 2.5xATR / target 2.0xATR, trend OFF ->
#     OOS net +$984 (PF 1.34, n50) | full 55d +$3,775 / 1 MNQ
#     full maxDD $1,178 (was $1,503), worst day -$369 (was -$715),
#     max loss streak 6 (was 15)  -- i.e. far more trend-day robust.
#  Edge still concentrates 09:00-13:00 CT; entries gated to 08:30-13:30 below.
$env:STRATEGY              = 'mean_reversion'
$env:POLL_INTERVAL_SECONDS = '10'
$env:MR_LOOKBACK           = '80'
$env:MR_Z_ENTRY            = '2.0'
$env:STOP_MODE             = 'atr'    # volatility-scaled stops (was 'fixed')
$env:ATR_PERIOD            = '14'
$env:STOP_ATR_MULT         = '2.5'    # stop  = 2.5 x ATR (wide enough to survive trend-day noise)
$env:TARGET_ATR_MULT       = '2.0'    # target = 2.0 x ATR
$env:STOP_POINTS           = '15'     # (unused in atr mode; kept as fixed-mode fallback)
$env:TARGET_POINTS         = '40'     # (unused in atr mode)
$env:COOLDOWN_SECONDS      = '60'
$env:MIN_HOLD_SECONDS      = '30'
$env:MAX_HOLD_SECONDS      = '0'
$env:TREND_FILTER          = 'false'  # OFF: slope filter stayed OOS-negative at every threshold
$env:SKIP_FIRST_MINUTES    = '0'
$env:ALLOW_LONG            = 'true'
$env:ALLOW_SHORT           = 'true'

# --- Session: entries across the 09:00-13:00 CT edge window ---
$env:SESSION_TZ              = 'America/Chicago'
$env:SESSION_OPEN            = '08:30'  # 09:30 ET cash open
$env:ENTRY_END               = '13:30'  # 14:30 ET: no NEW entries after this (skip pm bleed)
$env:SESSION_CLOSE           = '15:00'  # 16:00 ET
$env:FLATTEN_BEFORE_CLOSE_MIN = '5'

# --- Risk caps: combine-safe, halt BEFORE the 50K hard rules ---
$env:MAX_CONTRACTS_PER_TRADE = '2'     # MNQ. ATR stops are WIDER (bigger per-trade risk)
                                       # than the old fixed 15pt, so 1-ct 55d maxDD rose to
                                       # ~$1,178. At 2x the worst MODELED day is ~-$738 (under
                                       # the $800 daily cap below); multi-day DD is bounded by
                                       # the daily-loss + 5-consec-loss halts. (1 ct is the
                                       # ultra-safe option: ~$68/day, maxDD ~$1,178.)
                                       # ~2 MNQ -> ~$120/day backtest.
$env:MAX_TRADES_PER_DAY      = '8'     # ATR stops -> trades last longer, ~3/day; less churn
$env:DAILY_LOSS_LIMIT        = '800'   # tighter: 2 red days (=$1,600) stays under $1,800 trailing
$env:TRAILING_DRAWDOWN       = '1800'  # < combine $2,000 trailing MLL
$env:MAX_CONSECUTIVE_LOSSES  = '5'     # backtest max loss streak was 6; halt at 5 caps trend days
$env:DAILY_PROFIT_TARGET     = '700'   # bank a green day (consistency-safe at this size)
# Absolute account-balance floor: halts + flattens if live balance reaches
# this level, ACROSS restarts. Set to ~ (combine high-water mark - $1.8k).
# For a fresh $50k combine, 48200 halts ~$1.8k down. UPDATE before each run.
if (-not $env:MIN_ACCOUNT_EQUITY) { $env:MIN_ACCOUNT_EQUITY = '48200' }

# --- Isolated logs + trade journal ---
$env:LOG_DIR      = 'logs/morning_mnq_meanrev'
$env:JOURNAL_FILE = 'data/morning_mnq_meanrev.csv'
$env:LOG_LEVEL    = 'INFO'

Write-Host "=== MNQ Mean-Reversion (ATR stops 2.5x/2.0x, trend OFF) | acct $($env:ACCOUNT_ID) | MNQ x$($env:MAX_CONTRACTS_PER_TRADE) ===" -ForegroundColor Cyan
Write-Host "Python: $Py" -ForegroundColor DarkGray
Write-Host 'Entries 08:30-13:30 CT (09:30-14:30 ET); flat by 15:00 CT.' -ForegroundColor DarkGray
Write-Host 'PAPER_MODE=false -> LIVE SIM ORDERS on the combine.' -ForegroundColor Yellow

& $Py run_bot.py --non-interactive
