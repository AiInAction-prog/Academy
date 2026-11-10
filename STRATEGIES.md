# Strategies

> Educational example code for the AI in Action course. Practice account only. Not trading advice. The strategies aren't profitable as written.

Two example strategies ship with this repo. They exist to give you something real to build, run and fix with an AI coding tool. All entry rules and indicator math live in `bot/rules.py`; live loops are in `bot/strategy.py` (mean reversion) and `bot/strategy_vwap_trend.py` (VWAP trend).

---

## 1. Morning MNQ mean reversion

**Launcher:** `Run_Library/run_meanrev_morning_mnq.ps1`  
**Env:** `STRATEGY=mean_reversion`, `SYMBOL_ROOT=MNQ`

### Idea

When price stretches far from its recent average (high z-score), the code assumes it will snap back: it buys when price is far below the average and shorts when it's far above. New entries are limited to the morning session.

### Rules

1. Every ~10s, pull 1-min bars and compute z-score vs an 80-bar SMA.
2. **Long** when z ≤ −2.0; **short** when z ≥ +2.0.
3. Stops/targets use **ATR scaling** (not fixed points): stop = 2.5×ATR, target = 2.0×ATR.
4. Trend-slope filter is **off** by default.
5. New entries only **08:30–13:30 CT**; flat by **15:00 CT** (5 min buffer).
6. Server-side protective stop on every entry; software monitors target/revert exits.

### Launcher params

| Param | Value | Notes |
|-------|-------|-------|
| `MR_LOOKBACK` | 80 | Bars for SMA/z-score |
| `MR_Z_ENTRY` | 2.0 | Entry threshold |
| `STOP_MODE` | atr | Volatility-scaled stops |
| `STOP_ATR_MULT` / `TARGET_ATR_MULT` | 2.5 / 2.0 | |
| `MAX_CONTRACTS_PER_TRADE` | 2 | MNQ size |
| `DAILY_LOSS_LIMIT` | 800 | Halt for the day after this realized loss |
| `TRAILING_DRAWDOWN` | 1800 | Session drawdown cap |
| `DAILY_PROFIT_TARGET` | 700 | Halt for the day after this realized gain |

### Change history (2026-06-25)

Stops changed from a fixed 15 points to ATR-scaled stops. To see how a change behaves on past data before you make it, run:

```powershell
python tools/backtest.py --strategy mean_reversion --symbol MNQ --days 55 --commission 0.37
```

---

## 2. MES VWAP trend pullback

**Launcher:** `ES_Strategy/run_es_vwaptrend.ps1`  
**Env:** `STRATEGY=vwap_trend`, `SYMBOL_ROOT=MES`

### Idea

Trade **with** the trend, not against it. In a trending session (high ADX), the code buys pullbacks to session VWAP in an uptrend and sells rallies to VWAP in a downtrend.

### Rules

1. **Regime:** ADX ≥ 30 required (trending, not ranging).
2. **Direction:** Close above VWAP → long pullbacks only; below → short rallies only.
3. **Trigger:** Bar tags VWAP and closes back on the trend side (`VWAP_REQUIRE_REJECTION=true`).
4. **Stop:** Beyond VWAP by 4pt (band mode).
5. **Target:** 1.5R from entry risk.
6. **Cooldown:** 120s between trades; max 10/day.
7. Full RTH session 08:30–15:00 CT.

### Launcher params

| Param | Value | Notes |
|-------|-------|-------|
| `VWAP_TREND_ADX_MIN` | 30 | Trend gate |
| `VWAP_TREND_TARGET_R` | 1.5 | Reward:risk |
| `VWAP_STOP_BUFFER` | 4.0 | Points beyond VWAP |
| `SKIP_FIRST_MINUTES` | 0 | Open hour included |
| `MAX_CONTRACTS_PER_TRADE` | 5 | MES size |
| `DAILY_LOSS_LIMIT` | 900 | |
| `PAPER_MODE` | true default | Override to `false` to send orders to your Practice account |

### Change history (2026-06-23)

Target changed from 2.5R to 1.5R, and the first 30 minutes are no longer skipped. Backtest before changes:

```powershell
python tools/backtest.py --strategy vwap_trend --symbol MES --days 55 --commission 0.37
```

### Ops note

While in a position the bot polls every 10s; logs may be quiet between entries. Check broker position + server stop if unsure. Restart after flat picks up open-position reconciliation.

---

## Changing the code

1. Read what the bot did in the `data/*.csv` journals.
2. Describe the change to your AI coding tool and backtest it.
3. Update the launcher `.ps1` env vars.
4. Log what you changed and why in `Run_Library/SESSION_AUDIT_LOG.md`.

A backtest replays bars; it won't match what happens on the Practice account exactly, and it says nothing about future results.
