> **Educational example code for the AI in Action course. Practice account only. Not trading advice. The strategies aren't profitable as written. Provided as is, with no warranty.**
>
> Run this code only on your TopStep Practice account, never on a Combine evaluation, funded, real-money, brokerage or retirement account. The bot checks the account before it trades and refuses anything that isn't a Practice account. [Risk disclosure](https://ai-in-action.academy/risk)

# AI in Action: TopstepX example bots

Two example intraday futures bots on **TopstepX / ProjectX**, for practicing how to build, run and fix software with an AI coding tool. Each strategy is a PowerShell launcher that sets its parameters and runs the shared Python bot.

## What you need before you start

You do **not** need separate Topstep and ProjectX accounts. **TopstepX runs on the ProjectX API**: this bot connects to `api.topstepx.com` (Topstep's ProjectX endpoint).

### Accounts and credentials

| What | Required? | Where to get it |
|------|-----------|-----------------|
| **TopStep Practice account** | Yes | Comes with your TopStep subscription. Activate it in the Topstep dashboard under Accounts → Add Ons. Its name starts with `PRAC`. |
| **`TSX_USERNAME`** | Yes | Your **TopstepX login username** (not stored in git) |
| **`API_KEY`** | Yes | TopstepX → **Settings → API** → create an API key |
| **`ACCOUNT_ID`** | Optional | Your Practice account's id. Run `python discover-accounts.py` after filling `.env`. If you leave it blank, the bot uses your Practice account. |
| **TopstepX password** | No | Not used by the bot; auth is username + API key only |

Put username and API key in `.env` (copy from `.env.example`). **Never commit `.env`.**

### Keep your API key private

Your API key reaches **every** account on your TopstepX profile, not just the Practice account. Treat it like a password: never share it, paste it into a chat, email it, or commit it. This code never prints or logs it. If you think it's been exposed, delete it in TopstepX → Settings → API and generate a new one right away.

### One bot at a time

Run one bot at a time, on your Practice account. To try the other strategy, stop the first bot and start the second on another day.

### On your computer

- **Windows** (launchers are PowerShell)
- **Python 3.9+**
- Internet during session hours (REST + live quotes from TopstepX)

### You do not need

- A separate "Project X" signup (TopstepX *is* ProjectX)
- Contract IDs (front month is auto-resolved)
- TradingView or a separate market data feed
- Anyone else to hold your credentials. You keep them local in `.env`

---

## Quick start

1. Copy [`.env.example`](.env.example) to `.env` and add your TopstepX username + API key.
2. Install: `python -m venv .venv` then `.venv\Scripts\pip install -r requirements.txt`
3. Find your Practice account: `python discover-accounts.py`
4. Smoke test: `python run_bot.py --check`

See [SETUP.md](SETUP.md) for full setup steps.

## Daily run commands

Pick **one** bot for the day. Set your Practice account id before launching.

**MNQ morning mean reversion:**

```powershell
$env:ACCOUNT_ID='YOUR_PRACTICE_ACCOUNT_ID'
powershell -ExecutionPolicy Bypass -File Run_Library\run_meanrev_morning_mnq.ps1
```

**MES VWAP trend pullback** (paper mode by default; set `PAPER_MODE=false` to send orders to your Practice account):

```powershell
$env:ACCOUNT_ID='YOUR_PRACTICE_ACCOUNT_ID'
$env:PAPER_MODE='false'
powershell -ExecutionPolicy Bypass -File ES_Strategy\run_es_vwaptrend.ps1
```

`MIN_ACCOUNT_EQUITY` is an absolute balance floor: the bot halts and flattens if the account balance reaches it. Set it from your own Practice account balance.

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

After each session, add a row to [Run_Library/SESSION_AUDIT_LOG.md](Run_Library/SESSION_AUDIT_LOG.md) so you have a record of what you changed in the code and why.

## Operations

| Action | Command |
|--------|---------|
| Stop all bots | `powershell -ExecutionPolicy Bypass -File Run_Library\stop_bot.ps1` |
| Stop + flatten one account | `$env:ACCOUNT_ID='...'; powershell ... stop_bot.ps1` |
| Flatten only | `$env:ACCOUNT_ID='...'; powershell ... flatten_account.ps1` |
| Emergency halt | Create empty file `KILL_SWITCH` in repo root |

**Do not** close the PowerShell window without stopping the bot. Orphaned Python processes can duplicate trades.

## Backtesting

Read-only historical replay (uses your `.env` credentials to fetch bars):

```powershell
python tools/backtest.py --strategy mean_reversion --symbol MNQ --days 20 --commission 0.37
python tools/backtest.py --strategy vwap_trend --symbol MES --days 20 --commission 0.37
```

A backtest shows how the code behaves on past data. It is not a prediction and not a reason to trade anything.

## Repo layout

```
run_bot.py              # Python entry point
discover-accounts.py    # Lists your accounts and marks your Practice account
bot/                    # Broker, risk, execution, strategies
bot/practice_guard.py   # Refuses any account that isn't a TopStep Practice account
Run_Library/            # MNQ launcher + ops scripts + audit log
ES_Strategy/            # MES launcher only
tools/backtest.py       # Historical replay CLI
config/instruments.yaml # MNQ / MES contract specs
tests/                  # Unit tests (python -m unittest discover -s tests)
```

## Safety

- The bot prints `PRACTICE ACCOUNT ONLY. Not trading advice.` at startup, confirms the account is a TopStep Practice account (name starting `PRAC`), and refuses to start, or to send any order, otherwise. Don't remove that check.
- `PAPER_MODE=true` in `.env` simulates fills locally; nothing is sent to TopstepX.
- `PAPER_MODE=false` sends orders to your **Practice account**. The launchers use `--non-interactive` to skip the typed confirmation.
- Never commit `.env` or API keys.
