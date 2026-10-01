# Live-Sim Session Audit Log

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

## Example — 2026-06-26 (Fri)

### Setup
| Bot | Acct | Strategy / key params | Size | Start bal |
|---|---|---|---|---|
| MNQ | (your acct) | mean_reversion z2.0 lb80 ATR stop 2.5x/tgt 2.0x, trend OFF, entries 08:30-13:30 CT | 2 | $50,000 |
| MES | (your acct) | vwap_trend adx>=30 R1.5 band buf4 skip0, 08:30-15:00 CT | 5 | $50,000 |

### Result
| Bot | Trades | Net $ | Notes |
|---|---|---|---|
| MNQ | 0 | $0 | No z>=2 signal yet (first ATR-stop live day) |
| MES | 1 closed, 1 open | +$68.85 realized | SELL target hit; BUY still open at last check |

### Trade log
- 08:37 CT: SELL 5 @ target (+$90.62 gross). First entry had stop placement failure; bot flattened and retried.
- 09:52 CT: BUY 5 with server stop — open at last check.

### Retune / ops
- ES log went quiet while holding — normal (poll loop, no heartbeat on old builds). Fix: in-position monitoring + `reattach_open_position()` on restart. Restart ES bot after flat to pick up fixes.
- MNQ on ATR stops after 06-25 retune: fixed 15pt stops failed in trend regimes; ATR 2.5x/2.0x improved OOS on 55d backtest.

---

## Your entries below

(Add new sessions here, newest first.)
