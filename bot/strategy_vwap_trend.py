"""Strategy 4 - VWAP trend-pullback continuation (high frequency).

The mirror image of the VWAP fade family (Strategies 3 / 3B). Instead of fading
stretched moves back to VWAP in a range, this trades WITH an established trend by
buying shallow pullbacks to the session VWAP in an uptrend and selling rallies to
VWAP in a downtrend:

  - Regime gate is INVERTED vs the reverter: only act when ADX is high
    (``VWAP_TREND_ADX_MIN``), i.e. the market is trending.
  - Direction comes from price's side of VWAP: above => uptrend (long pullbacks),
    below => downtrend (short rallies).
  - Trigger: the latest CLOSED bar tags VWAP and closes back on the trend side
    (a ``band_rejection`` at the VWAP level) - a pullback that held.
  - Stop just beyond VWAP (or ATR); target = a fixed R-multiple of that risk
    (``VWAP_TREND_TARGET_R``), set at entry - NOT a moving VWAP.
  - NO per-side cap. After each exit a side re-arms once
    ``VWAP_TREND_COOLDOWN_SECONDS`` elapses; capped by ``VWAP_TREND_MAX_TRADES``.

Shares execution/risk/journaling/safety with the other strategies via
``bot.execution`` and ``bot.risk`` (server-side protective stops, kill switch,
reconciliation).
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, time as dtime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple
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
    reattach_open_position,
)
from .logger import log_event
from .marketstream import SignalRMarketStream
from .pricing import live_price
from .risk import HaltError, RiskGate, TradeOutcome
from .signals import adx, atr, band_rejection, session_vwap_bands

STRATEGY_NAME = "vwap_trend"


def _bar_dt(bar: Dict[str, Any], tz: ZoneInfo) -> Optional[datetime]:
    t = bar.get("t") or bar.get("timestamp")
    if t is None:
        return None
    if isinstance(t, (int, float)):
        return datetime.fromtimestamp(t / 1000.0, tz=timezone.utc).astimezone(tz)
    try:
        return datetime.fromisoformat(str(t).replace("Z", "+00:00")).astimezone(tz)
    except ValueError:
        return None


def _session_bars(
    bars: Sequence[Dict[str, Any]], tz: ZoneInfo, open_t: dtime, now_local: datetime
) -> List[Dict[str, Any]]:
    open_dt = now_local.replace(hour=open_t.hour, minute=open_t.minute,
                               second=0, microsecond=0)
    out = []
    for b in bars:
        dt = _bar_dt(b, tz)
        if dt is not None and open_dt <= dt <= now_local:
            out.append(b)
    return out


def _check_exit_trend(pos: OpenPosition, price: float) -> Optional[str]:
    """Fixed stop / R-multiple target (no moving VWAP target here)."""
    if pos.side == "BUY":
        if price <= pos.stop_price:
            return "STOP"
        if price >= pos.target_price:
            return "TARGET"
    else:
        if price >= pos.stop_price:
            return "STOP"
        if price <= pos.target_price:
            return "TARGET"
    return None


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

    starting_equity = get_balance(client, account_id) or 0.0
    gate.start_new_session(starting_equity)
    log_event(
        logger, "strategy.run_started",
        strategy=STRATEGY_NAME, contract_id=contract_id, size=size,
        paper_mode=settings.paper_mode,
        session=f"{sc.session_open}-{sc.session_close} {sc.session_tz}",
        vwap=(f"trend adx>= {sc.vwap_trend_adx_min}, target {sc.vwap_trend_target_r}R, "
              f"cooldown {sc.vwap_trend_cooldown_seconds}s, "
              f"max {sc.vwap_trend_max_trades}/day, stop {sc.vwap_stop_mode}"),
        starting_equity=starting_equity,
    )

    pos: Optional[OpenPosition] = None
    last_reconcile_mono = time.monotonic()
    last_position_log_mono = 0.0
    started = time.monotonic()
    trend_trades = 0
    last_exit_mono = 0.0
    cur_vwap: Optional[float] = None
    cur_day = datetime.now(tz).date()
    params_snapshot = (
        f"adxmin{sc.vwap_trend_adx_min},targetR{sc.vwap_trend_target_r},"
        f"cd{sc.vwap_trend_cooldown_seconds},stop{sc.vwap_stop_mode},"
        f"rej{int(sc.vwap_require_rejection)}"
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

    if not settings.paper_mode:
        attached = reattach_open_position(
            client, account_id, contract_id, sc.vwap_trend_target_r, logger,
        )
        if attached is not None:
            pos = attached
            trend_trades = max(trend_trades, 1)

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
            # Reset the per-day trade counter at the session rollover.
            if now_local.date() != cur_day:
                cur_day = now_local.date()
                trend_trades = 0
            within = in_session(now_local, open_t, close_t)
            mins_to_close = minutes_to_close(now_local, close_t)
            in_flatten_window = within and mins_to_close <= sc.flatten_before_close_min
            price = live_price(stream, client, contract_id).price

            if not within or in_flatten_window:
                if pos is not None and price is not None:
                    _do_exit(pos, price, "EOD")
                if within and in_flatten_window:
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
                # Fixed stop/target exits use live price only; skip the heavy
                # 720-bar fetch so we don't block exit checks or go silent.
                if not settings.paper_mode and not positions_on_contract(
                    client, account_id, contract_id
                ):
                    if pos.stop_order_id is not None:
                        client.cancel_order_safe(account_id, pos.stop_order_id)
                    _record_stop_filled(pos)
                    if gate.is_halted():
                        client.flatten_all(account_id)
                        break
                    time.sleep(sc.poll_interval_seconds)
                    continue

                held = time.monotonic() - pos.entry_mono
                reason = _check_exit_trend(pos, price)
                if reason is None and sc.max_hold_seconds > 0 and held >= sc.max_hold_seconds:
                    reason = "MAX_HOLD"
                if reason is not None:
                    if reason in ("STOP", "MAX_HOLD") or held >= sc.min_hold_seconds:
                        _do_exit(pos, price, reason)
                        if gate.is_halted():
                            client.flatten_all(account_id)
                            log_event(logger, "strategy.halted_after_close")
                            break

                if (not settings.paper_mode
                        and time.monotonic() - last_reconcile_mono >= 60.0):
                    bal = get_balance(client, account_id)
                    if bal is not None:
                        gate.reconcile_realized(bal - starting_equity)
                    last_reconcile_mono = time.monotonic()

                if time.monotonic() - last_position_log_mono >= 60.0:
                    pv = settings.instrument.point_value
                    unreal = (price - pos.entry_price) * pv * pos.size * pos.direction
                    log_event(
                        logger, "strategy.position_monitor",
                        side=pos.side, price=price, entry=pos.entry_price,
                        stop=pos.stop_price, target=pos.target_price,
                        unrealized=round(unreal, 2), held_s=round(held),
                    )
                    last_position_log_mono = time.monotonic()

                time.sleep(sc.poll_interval_seconds)
                continue

            # Flat: refresh VWAP + regime for new entries.
            try:
                need = max(sc.adx_period * 2 + 2, 60)
                bars = client.retrieve_bars(
                    contract_id, minutes_back=max(480, need), limit=720,
                )
            except BrokerError as exc:
                log_event(logger, "strategy.bars_error", error=str(exc))
                time.sleep(sc.poll_interval_seconds)
                continue

            sess = _session_bars(bars, tz, open_t, now_local)
            vb = session_vwap_bands(sess, 1.0) if sess else None
            if vb is not None:
                cur_vwap, _upper, _lower, _std = vb

            if (not settings.paper_mode
                    and time.monotonic() - last_reconcile_mono >= 60.0):
                bal = get_balance(client, account_id)
                if bal is not None:
                    gate.reconcile_realized(bal - starting_equity)
                last_reconcile_mono = time.monotonic()

            mins_since_open = -minutes_to_close(now_local, open_t)
            if sc.skip_first_minutes > 0 and mins_since_open < sc.skip_first_minutes:
                time.sleep(sc.poll_interval_seconds)
                continue
            if vb is None or cur_vwap is None or trend_trades >= sc.vwap_trend_max_trades:
                time.sleep(sc.poll_interval_seconds)
                continue
            # Re-arm cooldown: wait after an exit before trading again.
            if time.monotonic() - last_exit_mono < sc.vwap_trend_cooldown_seconds:
                time.sleep(sc.poll_interval_seconds)
                continue

            # Regime filter: only trade WITH the trend (high ADX).
            a = adx(bars, sc.adx_period)
            if a is None or a < sc.vwap_trend_adx_min:
                time.sleep(sc.poll_interval_seconds)
                continue

            closed = bars[:-1]
            last = closed[-1]
            last_close = float(last["c"])
            # Direction from the last closed bar's close vs VWAP.
            side = None
            if last_close > cur_vwap and sc.allow_long:
                side = "BUY"
            elif last_close < cur_vwap and sc.allow_short:
                side = "SELL"
            if side is None:
                time.sleep(sc.poll_interval_seconds)
                continue

            # Pullback-hold trigger: bar tagged VWAP and closed back on the
            # trend side (band_rejection at the VWAP level).
            if sc.vwap_require_rejection and not band_rejection(last, cur_vwap, side):
                log_event(logger, "strategy.vwap_no_pullback", side=side)
                time.sleep(sc.poll_interval_seconds)
                continue

            try:
                gate.check_can_open(size)
            except HaltError as exc:
                log_event(logger, "strategy.entry_blocked", reason=str(exc))
                time.sleep(sc.poll_interval_seconds)
                continue

            atr_val = atr(bars, sc.adx_period)
            vwap_at_entry = cur_vwap
            log_event(logger, "strategy.signal", action=side, price=price,
                      vwap=round(cur_vwap, 2), adx=round(a, 1))

            def _stop_target(fill: float, d: int) -> Tuple[float, float]:
                if sc.vwap_stop_mode == "atr" and atr_val:
                    stop = fill - d * (atr_val * sc.stop_atr_mult)
                else:  # band: stop just beyond VWAP on the wrong side
                    stop = vwap_at_entry - d * sc.vwap_stop_buffer
                risk = (fill - stop) * d
                if risk <= 0:
                    # Degenerate geometry; fall back to a buffer-sized risk.
                    risk = max(sc.vwap_stop_buffer, 1e-6)
                    stop = fill - d * risk
                target = fill + d * sc.vwap_trend_target_r * risk
                return stop, target

            new_pos = open_position(
                settings, client, account_id, contract_id,
                side, size, price, _stop_target, logger,
                strategy=STRATEGY_NAME, atr_val=atr_val,
                entry_hour=now_local.hour,
                extra_log={"vwap": round(cur_vwap, 2), "adx": round(a, 1)},
            )
            if new_pos is not None:
                pos = new_pos
                trend_trades += 1

            time.sleep(sc.poll_interval_seconds)

    finally:
        if pos is not None:
            try:
                px = live_price(stream, client, contract_id).price or pos.entry_price
                _do_exit(pos, px, "SHUTDOWN")
            except BrokerError as exc:
                log_event(logger, "strategy.shutdown_exit_error", error=str(exc))
                client.flatten_all(account_id)
