"""Strategy 1 - Mean-reversion runner, risk-gated, with live SignalR pricing.

Logic:
  - Compute SMA + z-score over the last ``lookback`` 1-minute closes.
  - Enter LONG when z <= -z_entry (oversold), SHORT when z >= z_entry (overbought).
  - Exit on hard stop, fixed target, or revert through the entry SMA.
  - Trend filter blocks fading a strong trend; min-hold + cooldown throttle churn.
  - Only trade inside the session window; force flat before the close.

Execution, server-side protective stops, session math, and journaling live in
``bot.execution`` (shared with other strategies). This module holds only the
mean-reversion decision logic.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

from .broker import BrokerError, TopstepXClient
from .config import Settings
from .execution import (
    OpenPosition,
    close_position,
    get_balance,
    in_session,
    journal_trade,
    minutes_to_close,
    open_position,
    parse_hhmm,
    positions_on_contract,
)
from .logger import log_event
from .marketstream import SignalRMarketStream
from .pricing import live_price
from .risk import HaltError, RiskGate, TradeOutcome
from .signals import atr, mean_reversion_signal, passes_trend_filter

STRATEGY_NAME = "mean_reversion"


# ---------------------------------------------------------------- exit checks


def _check_exit(pos: OpenPosition, price: float, target_points: float) -> Optional[str]:
    pnl_points = (price - pos.entry_price) * pos.direction
    if pos.side == "BUY" and price <= pos.stop_price:
        return "STOP"
    if pos.side == "SELL" and price >= pos.stop_price:
        return "STOP"
    if pnl_points >= target_points:
        return "TARGET"
    if pos.sma_at_entry is not None:
        if pos.side == "BUY" and price >= pos.sma_at_entry:
            return "SMA_REVERT"
        if pos.side == "SELL" and price <= pos.sma_at_entry:
            return "SMA_REVERT"
    return None


def _stop_target_distances(sc, atr_val: Optional[float]) -> Tuple[float, float]:
    """Return (stop_distance, target_distance) in points per the configured mode."""
    if sc.stop_mode == "atr" and atr_val is not None and atr_val > 0:
        return atr_val * sc.stop_atr_mult, atr_val * sc.target_atr_mult
    return sc.stop_points, sc.target_points


# ----------------------------------------------------------------- main loop


def run(
    settings: Settings,
    client: TopstepXClient,
    gate: RiskGate,
    account_id: int,
    contract_id: str,
    stream: Optional[SignalRMarketStream],
    logger: logging.Logger,
    max_runtime_s: Optional[float] = None,
) -> None:
    sc = settings.strategy
    size = max(1, settings.risk.max_contracts_per_trade)
    tz = ZoneInfo(sc.session_tz)
    open_t = parse_hhmm(sc.session_open)
    close_t = parse_hhmm(sc.session_close)
    entry_end_t = parse_hhmm(sc.entry_end) if sc.entry_end else None

    starting_equity = get_balance(client, account_id) or 0.0
    gate.start_new_session(starting_equity)
    log_event(
        logger, "strategy.run_started",
        strategy=STRATEGY_NAME, contract_id=contract_id, size=size,
        paper_mode=settings.paper_mode,
        session=f"{sc.session_open}-{sc.session_close} {sc.session_tz}",
        starting_equity=starting_equity,
    )

    pos: Optional[OpenPosition] = None
    last_exit_mono = 0.0
    last_reconcile_mono = time.monotonic()
    started = time.monotonic()
    params_snapshot = (
        f"z{sc.z_entry},lb{sc.lookback},stopmode{sc.stop_mode},"
        f"stop{sc.stop_points},tgt{sc.target_points},trend{int(sc.trend_filter)}"
    )

    def _do_exit(p: OpenPosition, px: float, reason: str) -> None:
        nonlocal pos, last_exit_mono
        pnl = close_position(settings, client, account_id, contract_id, p, px, reason,
                             logger, STRATEGY_NAME)
        gate.record_trade(TradeOutcome(pnl=pnl, closed_at=datetime.now(timezone.utc),
                                       contract_id=contract_id, size=p.size))
        journal_trade(settings, tz, contract_id, p, px, reason, pnl,
                      STRATEGY_NAME, params_snapshot)
        pos = None
        last_exit_mono = time.monotonic()

    def _record_stop_filled(p: OpenPosition) -> None:
        nonlocal pos, last_exit_mono
        pv = settings.instrument.point_value
        pnl = (p.stop_price - p.entry_price) * pv * p.size * p.direction
        log_event(logger, "strategy.server_stop_filled",
                  entry=p.entry_price, stop=p.stop_price, pnl=round(pnl, 2))
        gate.record_trade(TradeOutcome(pnl=pnl, closed_at=datetime.now(timezone.utc),
                                       contract_id=contract_id, size=p.size))
        journal_trade(settings, tz, contract_id, p, p.stop_price, "SERVER_STOP", pnl,
                      STRATEGY_NAME, params_snapshot)
        pos = None
        last_exit_mono = time.monotonic()

    try:
        while True:
            if max_runtime_s is not None and time.monotonic() - started > max_runtime_s:
                log_event(logger, "strategy.max_runtime_reached")
                break

            if gate.kill_switch_tripped() or gate.is_halted():
                px = live_price(stream, client, contract_id).price
                if pos is not None and px is not None:
                    _do_exit(pos, px, "HALT")
                client.flatten_all(account_id)
                log_event(logger, "strategy.halted_stop", halted=gate.is_halted())
                break

            now_local = datetime.now(tz)
            within = in_session(now_local, open_t, close_t)
            mins_to_close = minutes_to_close(now_local, close_t)
            in_flatten_window = within and mins_to_close <= sc.flatten_before_close_min

            price = live_price(stream, client, contract_id).price

            if not within or in_flatten_window:
                if pos is not None and price is not None:
                    _do_exit(pos, price, "EOD")
                if within and in_flatten_window:
                    log_event(logger, "strategy.flatten_window",
                              mins_to_close=round(mins_to_close, 1))
                    time.sleep(sc.poll_interval_seconds)
                    continue
                if not within and now_local.time() >= close_t:
                    log_event(logger, "strategy.session_closed")
                    break
                time.sleep(sc.poll_interval_seconds)
                continue

            if price is None:
                time.sleep(sc.poll_interval_seconds)
                continue

            if pos is not None:
                # Server-side protective stop already fired? (live only)
                if not settings.paper_mode and not positions_on_contract(
                    client, account_id, contract_id
                ):
                    if pos.stop_order_id is not None:
                        client.cancel_order_safe(account_id, pos.stop_order_id)
                    _record_stop_filled(pos)
                    if gate.is_halted():
                        client.flatten_all(account_id)
                        log_event(logger, "strategy.halted_after_close")
                        break
                    time.sleep(sc.poll_interval_seconds)
                    continue

                held = time.monotonic() - pos.entry_mono
                reason = _check_exit(pos, price, sc.target_points)
                if reason is None and sc.max_hold_seconds > 0 and held >= sc.max_hold_seconds:
                    reason = "MAX_HOLD"
                if reason is not None:
                    if reason in ("STOP", "MAX_HOLD") or held >= sc.min_hold_seconds:
                        _do_exit(pos, price, reason)
                        if gate.is_halted():
                            client.flatten_all(account_id)
                            log_event(logger, "strategy.halted_after_close")
                            break
            else:
                if (not settings.paper_mode
                        and time.monotonic() - last_reconcile_mono >= 60.0):
                    bal = get_balance(client, account_id)
                    if bal is not None:
                        gate.reconcile_realized(bal - starting_equity)
                    last_reconcile_mono = time.monotonic()

                # No NEW entries after the entry-end cutoff (still manage/flatten
                # any open position until the session close).
                if entry_end_t is not None and now_local.time() >= entry_end_t:
                    time.sleep(sc.poll_interval_seconds)
                    continue

                mins_since_open = -minutes_to_close(now_local, open_t)
                if sc.skip_first_minutes > 0 and mins_since_open < sc.skip_first_minutes:
                    time.sleep(sc.poll_interval_seconds)
                    continue

                if time.monotonic() - last_exit_mono >= sc.cooldown_seconds:
                    try:
                        need = max(sc.lookback, sc.trend_lookback, sc.atr_period) + 5
                        bars = client.retrieve_bars(
                            contract_id, minutes_back=max(need, 90), limit=max(need, 120),
                        )
                        closes = [float(b["c"]) for b in bars if b.get("c") is not None]
                        action, sma, z = mean_reversion_signal(closes, sc.lookback, sc.z_entry)
                        atr_val = atr(bars, sc.atr_period)
                        if action == "BUY" and not sc.allow_long:
                            action = "HOLD"
                        if action == "SELL" and not sc.allow_short:
                            action = "HOLD"
                        if (action in ("BUY", "SELL") and sc.trend_filter
                                and not passes_trend_filter(
                                    action, closes, sc.trend_lookback, sc.trend_slope_thresh)):
                            log_event(logger, "strategy.trend_filter_block", action=action)
                            action = "HOLD"
                        if action in ("BUY", "SELL") and sma is not None:
                            try:
                                gate.check_can_open(size)
                            except HaltError as exc:
                                log_event(logger, "strategy.entry_blocked", reason=str(exc))
                            else:
                                log_event(logger, "strategy.signal", action=action,
                                          z=round(z, 2) if z is not None else None,
                                          price=price, sma=round(sma, 2))
                                stop_dist, target_dist = _stop_target_distances(sc, atr_val)
                                new_pos = open_position(
                                    settings, client, account_id, contract_id,
                                    action, size, price,
                                    lambda fill, d: (fill - d * stop_dist,
                                                     fill + d * target_dist),
                                    logger, strategy=STRATEGY_NAME,
                                    sma=sma, z=z, atr_val=atr_val,
                                    entry_hour=now_local.hour,
                                    extra_log={"stop_mode": sc.stop_mode,
                                               "atr": round(atr_val, 2) if atr_val else None,
                                               "sma": round(sma, 2)},
                                )
                                if new_pos is not None:
                                    pos = new_pos
                    except BrokerError as exc:
                        log_event(logger, "strategy.bars_error", error=str(exc))

            time.sleep(sc.poll_interval_seconds)

    finally:
        if pos is not None:
            try:
                px = live_price(stream, client, contract_id).price or pos.entry_price
                _do_exit(pos, px, "SHUTDOWN")
            except BrokerError as exc:
                log_event(logger, "strategy.shutdown_exit_error", error=str(exc))
                client.flatten_all(account_id)
