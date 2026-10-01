"""Backtest mean-reversion or VWAP-trend over recent historical bars.

Run::

    python tools/backtest.py --strategy mean_reversion --symbol MNQ --days 10
    python tools/backtest.py --strategy vwap_trend --symbol MES --days 20 --commission 0.37

Read-only: places no orders.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bot.backtest import (  # noqa: E402
    BacktestParams,
    VwapTrendParams,
    fetch_history,
    run_backtest,
    run_vwap_trend_backtest,
)
from bot.broker import BrokerError, TopstepXClient  # noqa: E402
from bot.config import load_settings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(prog="backtest")
    parser.add_argument("--days", type=int, default=10)
    parser.add_argument(
        "--strategy",
        choices=["mean_reversion", "vwap_trend"],
        default=None,
        help="Strategy to backtest (default: STRATEGY from .env).",
    )
    parser.add_argument(
        "--symbol",
        choices=["MNQ", "MES"],
        default=None,
        help="Instrument root (default: SYMBOL_ROOT from .env).",
    )
    parser.add_argument("--contract", default=None, help="Explicit contract id.")
    parser.add_argument("--commission", type=float, default=0.0, help="Per side, per contract.")
    parser.add_argument("--slippage-ticks", type=float, default=1.0)
    parser.add_argument("--z", type=float, default=None)
    parser.add_argument("--lookback", type=int, default=None)
    parser.add_argument("--stop", type=float, default=None)
    parser.add_argument("--target", type=float, default=None)
    parser.add_argument("--no-trend", action="store_true", help="Disable trend filter.")
    parser.add_argument("--save", action="store_true", help="Save report JSON under data/backtests/.")
    args = parser.parse_args()

    settings = load_settings()
    sc = settings.strategy
    strategy = args.strategy or sc.name
    if strategy not in ("mean_reversion", "vwap_trend"):
        print(f"Unsupported strategy: {strategy}", file=sys.stderr)
        return 2

    symbol = args.symbol or settings.symbol_root
    os.environ["SYMBOL_ROOT"] = symbol
    settings = load_settings()

    client = TopstepXClient(settings)
    try:
        client.authenticate()
        contract_id = (
            args.contract
            or settings.contract_id
            or client.resolve_front_month(symbol)
        )
    except BrokerError as exc:
        print(f"Auth/contract error: {exc}", file=sys.stderr)
        return 1

    print(f"Fetching ~{args.days} day(s) of 1-min bars for {contract_id} ({strategy}) ...")
    bars = fetch_history(client, contract_id, args.days)
    print(f"  got {len(bars)} bars")
    if len(bars) < 200:
        print("Not enough bars to backtest.", file=sys.stderr)
        return 2

    if strategy == "vwap_trend":
        params = VwapTrendParams(
            adx_min=sc.vwap_trend_adx_min,
            target_r=sc.vwap_trend_target_r,
            vwap_require_rejection=sc.vwap_require_rejection,
            adx_period=sc.adx_period,
            vwap_stop_mode=sc.vwap_stop_mode,
            vwap_stop_buffer=sc.vwap_stop_buffer,
            vwap_max_trades=sc.vwap_trend_max_trades,
            cooldown_seconds=sc.vwap_trend_cooldown_seconds,
            stop_atr_mult=sc.stop_atr_mult,
            skip_first_minutes=sc.skip_first_minutes,
            allow_long=sc.allow_long,
            allow_short=sc.allow_short,
            session_tz=sc.session_tz,
            session_open=sc.session_open,
            session_close=sc.session_close,
        )
        result = run_vwap_trend_backtest(
            bars, params, settings.instrument,
            commission_per_side=args.commission, slippage_ticks=args.slippage_ticks,
        )
    else:
        params = BacktestParams(
            lookback=args.lookback if args.lookback is not None else sc.lookback,
            z_entry=args.z if args.z is not None else sc.z_entry,
            stop_mode=sc.stop_mode,
            stop_points=args.stop if args.stop is not None else sc.stop_points,
            target_points=args.target if args.target is not None else sc.target_points,
            atr_period=sc.atr_period,
            stop_atr_mult=sc.stop_atr_mult,
            target_atr_mult=sc.target_atr_mult,
            trend_filter=(not args.no_trend) and sc.trend_filter,
            trend_lookback=sc.trend_lookback,
            trend_slope_thresh=sc.trend_slope_thresh,
            allow_long=sc.allow_long,
            allow_short=sc.allow_short,
            session_tz=sc.session_tz,
            session_open=sc.session_open,
            session_close=sc.session_close,
            skip_first_minutes=sc.skip_first_minutes,
        )
        result = run_backtest(
            bars, params, settings.instrument,
            commission_per_side=args.commission, slippage_ticks=args.slippage_ticks,
        )

    summary = result.summary()
    print("\n=== Backtest result ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")

    if args.save:
        out_dir = REPO_ROOT / "data" / "backtests"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = out_dir / f"backtest_{stamp}.json"
        path.write_text(json.dumps({
            "contract_id": contract_id,
            "strategy": strategy,
            "symbol": symbol,
            "days": args.days,
            "params": params.__dict__,
            "commission_per_side": args.commission,
            "slippage_ticks": args.slippage_ticks,
            "summary": summary,
            "trades": [t.__dict__ for t in result.trades],
        }, indent=2, default=str), encoding="utf-8")
        print(f"\nSaved {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
