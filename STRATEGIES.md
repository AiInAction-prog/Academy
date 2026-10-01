# Strategies

Two starter strategies ship with this repo. All signal math lives in `bot/signals.py`; live loops are in `bot/strategy.py` (mean reversion) and `bot/strategy_vwap_trend.py` (VWAP trend).

---

## 1. Morning MNQ mean reversion

**Launcher:** `Run_Library/run_meanrev_morning_mnq.ps1`  
**Env:** `STRATEGY=mean_reversion`, `SYMBOL_ROOT=MNQ`

### Idea

When price stretches far from its recent average (high z-score), bet on a snap back — buy oversold, short overbought. Edge concentrates in the cash-open morning; afternoon entries are gated off.

### Rules

1. Every ~10s, pull 1-min bars and compute z-score vs an 80-bar SMA.
2. **Long** when z ≤ −2.0; **short** when z ≥ +2.0.
3. Stops/targets use **ATR scaling** (not fixed points): stop = 2.5×ATR, target = 2.0×ATR.
4. Trend-slope filter is **off** (tested OOS-negative on recent data).
5. New entries only **08:30–13:30 CT**; flat by **15:00 CT** (5 min buffer).
6. Server-side protective stop on every entry; software monitors target/revert exits.

### Key launcher params

| Param | Value | Notes |
|-------|-------|-------|
| `MR_LOOKBACK` | 80 | Bars for SMA/z-score |
| `MR_Z_ENTRY` | 2.0 | Entry threshold |
| `STOP_MODE` | atr | Volatility-scaled stops |
| `STOP_ATR_MULT` / `TARGET_ATR_MULT` | 2.5 / 2.0 | |
| `MAX_CONTRACTS_PER_TRADE` | 2 | MNQ size |
| `DAILY_LOSS_LIMIT` | 800 | |
| `TRAILING_DRAWDOWN` | 1800 | Under $2K combine rule |
| `DAILY_PROFIT_TARGET` | 700 | Bank green days |

### Retune note (2026-06-25)

Fixed 15pt stops went OOS-negative in trending regimes. ATR stops flipped OOS positive and cut worst-day loss. Before changing stops/size, run:

```powershell
python tools/backtest.py --strategy mean_reversion --symbol MNQ --days 55 --commission 0.37
```

---

## 2. MES VWAP trend pullback

**Launcher:** `ES_Strategy/run_es_vwaptrend.ps1`  
**Env:** `STRATEGY=vwap_trend`, `SYMBOL_ROOT=MES`

### Idea

Trade **with** the trend, not against it. In a trending session (high ADX), buy pullbacks to session VWAP in an uptrend and sell rallies to VWAP in a downtrend.

### Rules

1. **Regime:** ADX ≥ 30 required (trending, not ranging).
2. **Direction:** Close above VWAP → long pullbacks only; below → short rallies only.
3. **Trigger:** Bar tags VWAP and closes back on the trend side (`VWAP_REQUIRE_REJECTION=true`).
4. **Stop:** Beyond VWAP by 4pt (band mode).
5. **Target:** 1.5R from entry risk.
6. **Cooldown:** 120s between trades; max 10/day.
7. Full RTH session 08:30–15:00 CT.

### Key launcher params

| Param | Value | Notes |
|-------|-------|-------|
| `VWAP_TREND_ADX_MIN` | 30 | Trend gate |
| `VWAP_TREND_TARGET_R` | 1.5 | Reward:risk |
| `VWAP_STOP_BUFFER` | 4.0 | Points beyond VWAP |
| `SKIP_FIRST_MINUTES` | 0 | Open hour included |
| `MAX_CONTRACTS_PER_TRADE` | 5 | MES size |
| `DAILY_LOSS_LIMIT` | 900 | |
| `PAPER_MODE` | true default | Override to `false` for live sim |

### Retune note (2026-06-23)

Prior config (2.5R target, skip first 30 min) traded ~0/day. R1.5 + skip0 improved trade count and OOS robustness on ~55d MES data.

Backtest before changes:

```powershell
python tools/backtest.py --strategy vwap_trend --symbol MES --days 55 --commission 0.37
```

### Ops note

While in a position the bot polls every 10s; logs may be quiet between entries. Check broker position + server stop if unsure. Restart after flat picks up open-position reconciliation.

---

## Tuning workflow

1. Note live results in `data/*.csv` journals.
2. Backtest candidate param changes.
3. Update the launcher `.ps1` env vars.
4. Log setup + outcome in `Run_Library/SESSION_AUDIT_LOG.md`.

Do not expect backtest P&L to match live exactly — bar replay is directional evidence, not tick-perfect.
