# Practice Session Log

> PRACTICE ACCOUNT ONLY. Not trading advice. This log is your own record of what the code did and what you changed.

Running log of each trading day so configs can be retuned from accumulated evidence (not a single day). **Newest entry on top.**

## How to use this log

After each session (or at end of day), add an entry with:

1. **Setup** — account, strategy, key params, size, starting balance
2. **Result** — trades, net P&L, notes
3. **Trade log** — notable fills, errors, ops issues
4. **Retune actions** — what you changed and why (link backtest if you ran one)

Authoritative per-trade records:

| Bot | Journal |
|-----|---------|
| MNQ mean reversion | `data/morning_mnq_meanrev.csv` |
| MES VWAP trend | `data/es_vwaptrend.csv` |

Before changing launcher params, run `tools/backtest.py` and paste summary metrics into your retune section.

---

## Template (copy for each new day)

### YYYY-MM-DD (Day) — short title

#### Setup
| Bot | Acct | Strategy / key params | Size | Start bal |
|---|---|---|---|---|
| MNQ | | mean_reversion z__ lb__ ATR __/__ | | |
| MES | | vwap_trend adx>=__ R__ band buf__ | | |

#### Result
| Bot | Trades | Net $ | Notes |
|---|---|---|---|
| MNQ | | | |
| MES | | | |
| **Total** | | | |

#### Trade log
- (time CT): ...

#### Retune / ops
- ...

---

## Your entries below

(Add new sessions here, newest first.)
