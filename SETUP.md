# Setup: TopstepX / ProjectX API

> Educational example code for the AI in Action course. Practice account only. Not trading advice. Run it only on your TopStep Practice account, never on a Combine evaluation, funded, real-money, brokerage or retirement account.

## 1. TopstepX credentials

1. Activate your free **TopstepX Practice account**: Topstep dashboard → Accounts → Add Ons → TopstepX Practice Account. Its name starts with `PRAC`.
2. Log in to [TopstepX](https://www.topstepx.com).
3. Open **Settings → API** and create an API key.
4. Note your **login username** (not email, unless they are the same).

## 2. Keep your API key private

Your API key can place orders on **every** account on your TopstepX profile, including any Combine you hold. Treat it like a password:

- Keep it only in your local `.env` file. `.env` is in `.gitignore`, so it never reaches GitHub.
- Never paste it into a chat, an email, a support request, a screenshot or a course community. I will never ask for it.
- If you think it's been exposed, go to TopstepX → Settings → API, delete the key, and generate a new one right away. Then put the new key in `.env`.

This code never prints or logs your key.

## 3. Local environment

```powershell
cd "path\to\this\repo"
copy .env.example .env
```

Edit `.env`:

```dotenv
TSX_USERNAME=your_username
API_KEY=your_api_key
TSX_ENV=live
PAPER_MODE=true
```

`TSX_ENV=live` uses `api.topstepx.com`, the TopstepX gateway your Practice account is on.

## 4. Python virtual environment

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

Requires Python 3.9+ (for `zoneinfo`; `tzdata` covers Windows IANA names).

## 5. Find your Practice account

```powershell
.venv\Scripts\python.exe discover-accounts.py
```

It lists every account your key can see, marks your Practice account "use this one", and marks everything else "skipped". Copy the Practice account's id into `.env`:

```dotenv
ACCOUNT_ID=12345678
```

Or leave `ACCOUNT_ID` blank and the bot picks your Practice account itself.

## 6. Smoke test

```powershell
$env:SYMBOL_ROOT='MNQ'
.venv\Scripts\python.exe run_bot.py --check
```

You should see `PRACTICE ACCOUNT ONLY. Not trading advice.`, authentication success, your Practice account confirmed, contract resolution, and a live or REST quote. If you see `REFUSED`, the account isn't a Practice account: run step 5 again.

## 7. Paper vs Practice account orders

| Mode | Behavior |
|------|----------|
| `PAPER_MODE=true` | Orders simulated in-process; nothing sent to TopstepX |
| `PAPER_MODE=false` | Orders sent to your TopStep Practice account |

The MNQ launcher sets `PAPER_MODE=false`. The MES launcher defaults to paper unless you override it (as in the README daily command).

Interactive runs without `--non-interactive` require typing `I UNDERSTAND` when `PAPER_MODE=false`.

## 8. Settings the launchers set

Launchers set these per strategy; you normally edit the `.ps1` file, not `.env`. They're there so you can see where each setting lives in the code. They aren't recommendations.

| Variable | Purpose |
|----------|---------|
| `MIN_ACCOUNT_EQUITY` | Halt + flatten if the account balance reaches this floor |
| `DAILY_LOSS_LIMIT` | Max realized loss per day before halt |
| `TRAILING_DRAWDOWN` | Session drawdown cap |
| `MAX_CONTRACTS_PER_TRADE` | Size per entry |
| `MAX_TRADES_PER_DAY` | Trade count cap |

## 9. Troubleshooting

| Problem | Fix |
|---------|-----|
| `Missing required env var TSX_USERNAME` | Fill `.env` |
| `REFUSED: ... is not a TopStep Practice account` | Set `ACCOUNT_ID` to your Practice account (step 5), or leave it blank |
| `No active Practice account visible` | Activate the TopstepX Practice account (step 1) |
| `another bot instance is already running` | Run `stop_bot.ps1` or delete stale `data/.bot_acct_*.lock` after confirming no bot is running |
| No live quote | Normal on cold start; bot falls back to REST bars |

## Next steps

- Read [STRATEGIES.md](STRATEGIES.md) for how each example strategy is built.
- Run one launcher with paper mode first.
- Log each session in [Run_Library/SESSION_AUDIT_LOG.md](Run_Library/SESSION_AUDIT_LOG.md).
