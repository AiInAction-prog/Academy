# Setup — TopstepX / ProjectX API

## 1. TopstepX credentials

1. Log in to [TopstepX](https://www.topstepx.com).
2. Open **Settings → API** and create an API key.
3. Note your **login username** (not email, unless they are the same).

## 2. Local environment

```powershell
cd "path\to\Lean - Bots"
copy .env.example .env
```

Edit `.env`:

```dotenv
TSX_USERNAME=your_username
API_KEY=your_api_key
TSX_ENV=live
PAPER_MODE=true
```

`TSX_ENV=live` uses `api.topstepx.com` (combine / funded accounts). Use `demo` only if you have a demo gateway account.

## 3. Python virtual environment

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

Requires Python 3.9+ (for `zoneinfo`; `tzdata` covers Windows IANA names).

## 4. Discover account IDs

```powershell
.venv\Scripts\python.exe discover-accounts.py
```

Copy the numeric **id** for each combine you want to trade. Pass it at runtime:

```powershell
$env:ACCOUNT_ID='12345678'
```

Or set `ACCOUNT_ID=` in `.env` if you only run one account.

## 5. Smoke test

```powershell
$env:SYMBOL_ROOT='MNQ'
$env:ACCOUNT_ID='your_account_id'
.venv\Scripts\python.exe run_bot.py --check
```

You should see authentication success, contract resolution, and a live or REST quote.

## 6. Paper vs live sim

| Mode | Behavior |
|------|----------|
| `PAPER_MODE=true` | Orders simulated in-process; nothing sent to broker |
| `PAPER_MODE=false` | Real orders on your TopstepX combine |

The MNQ launcher sets `PAPER_MODE=false` (live sim). The MES launcher defaults to paper unless you override (as in the README daily command).

Interactive runs without `--non-interactive` require typing `I UNDERSTAND` when `PAPER_MODE=false`.

## 7. Risk env vars (set by launchers)

Launchers set these per strategy; you normally edit the `.ps1` file, not `.env`:

| Variable | Purpose |
|----------|---------|
| `MIN_ACCOUNT_EQUITY` | Halt + flatten if balance hits this floor (e.g. `48200` on a $50K combine) |
| `DAILY_LOSS_LIMIT` | Max realized loss per day before halt |
| `TRAILING_DRAWDOWN` | Session drawdown cap (keep under combine rule, e.g. `1800`) |
| `MAX_CONTRACTS_PER_TRADE` | Size per entry |
| `MAX_TRADES_PER_DAY` | Trade count cap |

## 8. Troubleshooting

| Problem | Fix |
|---------|-----|
| `Missing required env var TSX_USERNAME` | Fill `.env` |
| `Multiple accounts visible` | Set `ACCOUNT_ID` |
| `another bot instance is already running` | Run `stop_bot.ps1` or delete stale `data/.bot_acct_*.lock` after confirming no bot is running |
| No live quote | Normal on cold start; bot falls back to REST bars |

## Next steps

- Read [STRATEGIES.md](STRATEGIES.md) for strategy rules and tuning knobs.
- Run one launcher with paper mode first.
- Log each session in [Run_Library/SESSION_AUDIT_LOG.md](Run_Library/SESSION_AUDIT_LOG.md).
