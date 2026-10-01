# Algo Trading 101 — TopstepX Starter Bots

Two intraday futures strategies on **TopstepX / ProjectX**, sized for a **$50K combine** ($2,000 trailing drawdown). Each strategy is a PowerShell launcher that sets risk params and runs the shared Python bot.

## What you need before you start

You do **not** need separate Topstep and ProjectX accounts. **TopstepX runs on the ProjectX API** — this bot connects to `api.topstepx.com` (Topstep’s ProjectX endpoint).

### Accounts and credentials

| What | Required? | Where to get it |
|------|-----------|-----------------|
| **Topstep combine or funded account** | Yes | [Topstep](https://www.topstep.com) — you trade via **TopstepX** |
| **`TSX_USERNAME`** | Yes | Your **TopstepX login username** (not stored in git) |
| **`API_KEY`** | Yes | TopstepX → **Settings → API** → create an API key |
| **`ACCOUNT_ID`** | Yes | Run `python discover-accounts.py` after filling `.env` |
| **TopstepX password** | No | Not used by the bot; auth is username + API key only |

Put username and API key in `.env` (copy from `.env.example`). **Never commit `.env`.**

### One vs two accounts

- **One account** — run one strategy at a time.
- **Two accounts** — run MNQ and MES bots at the same time (one combine per bot).

### On your computer

- **Windows** (launchers are PowerShell)
- **Python 3.9+**
- Internet during session hours (REST + live quotes from TopstepX)

### You do not need

- A separate “Project X” signup (TopstepX *is* ProjectX for combines)
- Contract IDs (front month is auto-resolved)
- TradingView or a separate market data feed
- Anyone else to hold your credentials — you keep them local in `.env`

### Recommended before live sim

| Setting | Example | Purpose |
|---------|---------|---------|
| `MIN_ACCOUNT_EQUITY` | `48200` on $50K | Halt if balance hits combine floor (~$1.8k down) |
| `PAPER_MODE` | `true` first | Local fake fills; `false` = real combine orders |

---

## Quick start

1. Copy [`.env.example`](.env.example) to `.env` and add your TopstepX username + API key.
2. Install: `python -m venv .venv` then `.venv\Scripts\pip install -r requirements.txt`
3. Find account IDs: `python discover-accounts.py`
4. Smoke test: `python run_bot.py --check`

See [SETUP.md](SETUP.md) for full setup steps.

## Daily run commands

Run each bot in its own terminal window. Set your account ID and equity floor before launching.

**MNQ morning mean reversion** (live sim by default):

```powershell
$env:ACCOUNT_ID='YOUR_MNQ_ACCOUNT'
$env:MIN_ACCOUNT_EQUITY='48200'
powershell -ExecutionPolicy Bypass -File Run_Library\run_meanrev_morning_mnq.ps1
```

**MES VWAP trend pullback** (set `PAPER_MODE=false` for live sim after paper testing):

```powershell
$env:ACCOUNT_ID='YOUR_MES_ACCOUNT'
$env:PAPER_MODE='false'
$env:MIN_ACCOUNT_EQUITY='48200'
powershell -ExecutionPolicy Bypass -File ES_Strategy\run_es_vwaptrend.ps1
```

`MIN_ACCOUNT_EQUITY` is an absolute balance floor (~$50K high-water minus $1,800). Update it if your combine balance changes.

## What each bot does

| Bot | Instrument | Strategy | Session (CT) |
|-----|------------|----------|--------------|
| Morning MNQ | MNQ micro Nasdaq | Z-score mean reversion, ATR stops | Entries 08:30–13:30, flat by 15:00 |
| ES VWAP trend | MES micro S&P | Trend pullback to session VWAP (ADX filter) | 08:30–15:00 |

Details: [STRATEGIES.md](STRATEGIES.md)

## Logs and journals

| Bot | Log dir | Trade journal |
|-----|---------|---------------|
| MNQ | `logs/morning_mnq_meanrev/` | `data/morning_mnq_meanrev.csv` |
| MES | `logs/es_vwaptrend/` | `data/es_vwaptrend.csv` |

After each session, add a row to [Run_Library/SESSION_AUDIT_LOG.md](Run_Library/SESSION_AUDIT_LOG.md) so you can tune from accumulated evidence.

## Operations

| Action | Command |
|--------|---------|
| Stop all bots | `powershell -ExecutionPolicy Bypass -File Run_Library\stop_bot.ps1` |
| Stop + flatten one account | `$env:ACCOUNT_ID='...'; powershell ... stop_bot.ps1` |
| Flatten only | `$env:ACCOUNT_ID='...'; powershell ... flatten_account.ps1` |
| Emergency halt | Create empty file `KILL_SWITCH` in repo root |

**Do not** close the PowerShell window without stopping the bot — orphaned Python processes can duplicate trades.

## Backtest before tuning

Read-only historical replay (uses your `.env` credentials to fetch bars):

```powershell
python tools/backtest.py --strategy mean_reversion --symbol MNQ --days 20 --commission 0.37
python tools/backtest.py --strategy vwap_trend --symbol MES --days 20 --commission 0.37
```

Edit params in the launcher `.ps1` files, backtest, then log changes in the session audit file.

## Repo layout

```
run_bot.py              # Python entry point
bot/                    # Broker, risk, execution, strategies
Run_Library/            # MNQ launcher + ops scripts + audit log
ES_Strategy/            # MES launcher only
tools/backtest.py       # Historical replay CLI
config/instruments.yaml # MNQ / MES contract specs
```

## Safety

- `PAPER_MODE=true` in `.env` simulates fills locally; launchers can override.
- `PAPER_MODE=false` places **real combine orders**. Use `--non-interactive` only in unattended launchers after you accept the risk.
- Never commit `.env` or API keys.
