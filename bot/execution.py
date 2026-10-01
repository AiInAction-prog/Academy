"""Shared execution + session + journaling helpers used by all strategy runners.

Keeps order placement, the server-side protective stop, fill/flat polling,
session-window math, and trade journaling in ONE place so every strategy
(mean reversion, ORB, ...) gets the same battle-tested safety behavior.

Decision logic stays in the individual strategy runners; this module only
executes what they decide.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, time as dtime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from .broker import TopstepXClient
from .config import Settings
from .journal import TradeRecord, record_trade as journal_record
from .logger import log_event


# ------------------------------------------------------------------- position


@dataclass
class OpenPosition:
    side: str                 # "BUY" (long) or "SELL" (short)
    entry_price: float
    size: int
    stop_price: float
    target_price: float
    entry_mono: float         # time.monotonic() at entry
    entry_dt: datetime
    stop_order_id: Optional[str] = None   # server-side protective stop (live only)
    sma_at_entry: Optional[float] = None
    z_at_entry: Optional[float] = None
    atr_at_entry: Optional[float] = None
    entry_hour: int = 0       # hour-of-day (session tz) at entry

    @property
    def direction(self) -> int:
        return 1 if self.side == "BUY" else -1

    @property
    def exit_side(self) -> str:
        return "SELL" if self.side == "BUY" else "BUY"


# --------------------------------------------------------------- broker utils


def get_balance(client: TopstepXClient, account_id: int) -> Optional[float]:
    for a in client.list_accounts(only_active=True):
        try:
            if int(a.get("id")) == int(account_id):
                return float(a.get("balance"))
        except (TypeError, ValueError):
            continue
    return None


def positions_on_contract(
    client: TopstepXClient, account_id: int, contract_id: str
) -> List[Dict[str, Any]]:
    out = []
    for p in client.list_open_positions(account_id):
        cid = p.get("contractId") or p.get("contract_id")
        if str(cid) == str(contract_id):
            out.append(p)
    return out


def position_avg(pos: List[Dict[str, Any]]) -> Optional[float]:
    for p in pos:
        avg = p.get("averagePrice") or p.get("avgPrice") or p.get("price")
        if avg is not None:
            try:
                return float(avg)
            except (TypeError, ValueError):
                pass
    return None


def wait_avg_fill(
    client: TopstepXClient, account_id: int, contract_id: str, timeout_s: float = 10.0
) -> Optional[float]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        avg = position_avg(positions_on_contract(client, account_id, contract_id))
        if avg is not None:
            return avg
        time.sleep(0.5)
    return None


def wait_flat(
    client: TopstepXClient, account_id: int, contract_id: str, timeout_s: float = 10.0
) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not positions_on_contract(client, account_id, contract_id):
            return True
        time.sleep(0.5)
    return not positions_on_contract(client, account_id, contract_id)


def reattach_open_position(
    client: TopstepXClient,
    account_id: int,
    contract_id: str,
    target_r: float,
    logger: logging.Logger,
) -> Optional[OpenPosition]:
    """Rebuild in-memory state from a broker-held position after a restart.

    Requires a resting protective stop so target geometry can be inferred.
    Returns None when flat or when stop metadata is missing.
    """
    pos_rows = positions_on_contract(client, account_id, contract_id)
    if not pos_rows:
        return None

    entry_price = position_avg(pos_rows)
    if entry_price is None:
        return None
    size = int(pos_rows[0].get("size") or 0)
    if size <= 0:
        return None

    stop_order_id: Optional[str] = None
    stop_price: Optional[float] = None
    for order in client.search_open_orders(account_id):
        cid = order.get("contractId") or order.get("contract_id")
        if str(cid) != str(contract_id):
            continue
        raw_stop = order.get("stopPrice")
        if raw_stop is None:
            continue
        try:
            stop_price = float(raw_stop)
        except (TypeError, ValueError):
            continue
        oid = order.get("id")
        stop_order_id = str(oid) if oid is not None else None
        break

    if stop_price is None:
        log_event(
            logger, "strategy.reattach_skipped",
            reason="no_protective_stop_on_broker",
            entry=entry_price, size=size,
        )
        return None

    if stop_price < entry_price:
        side = "BUY"
    elif stop_price > entry_price:
        side = "SELL"
    else:
        log_event(
            logger, "strategy.reattach_skipped",
            reason="stop_equals_entry", entry=entry_price, stop=stop_price,
        )
        return None

    direction = 1 if side == "BUY" else -1
    risk = abs(entry_price - stop_price)
    if risk <= 0:
        risk = 1e-6
    target_price = entry_price + direction * target_r * risk

    entry_dt = datetime.now(timezone.utc)
    raw_ts = pos_rows[0].get("creationTimestamp")
    if raw_ts is not None:
        try:
            entry_dt = datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00"))
        except ValueError:
            pass

    pos = OpenPosition(
        side=side,
        entry_price=entry_price,
        size=size,
        stop_price=stop_price,
        target_price=target_price,
        entry_mono=time.monotonic(),
        entry_dt=entry_dt,
        stop_order_id=stop_order_id,
    )
    log_event(
        logger, "strategy.position_reattached",
        side=side, size=size, fill=entry_price,
        stop=round(stop_price, 2), target=round(target_price, 2),
        stop_order_id=stop_order_id,
    )
    return pos


# ------------------------------------------------------------------- session


def parse_hhmm(text: str) -> dtime:
    hh, mm = text.split(":")
    return dtime(int(hh), int(mm))


def in_session(now_local: datetime, open_t: dtime, close_t: dtime) -> bool:
    if now_local.weekday() >= 5:  # Sat/Sun
        return False
    return open_t <= now_local.time() < close_t


def minutes_to_close(now_local: datetime, close_t: dtime) -> float:
    close_dt = now_local.replace(
        hour=close_t.hour, minute=close_t.minute, second=0, microsecond=0
    )
    return (close_dt - now_local).total_seconds() / 60.0


# ----------------------------------------------------------------- execution

# Callback: given the actual fill price and direction (+1/-1), return the
# absolute (stop_price, target_price). Lets each strategy define its own stop
# placement (fixed/ATR distance, opposite-of-range, R-multiple, ...).
StopTargetFn = Callable[[float, int], Tuple[float, float]]


def open_position(
    settings: Settings,
    client: TopstepXClient,
    account_id: int,
    contract_id: str,
    side: str,
    size: int,
    ref_price: float,
    stop_target_fn: StopTargetFn,
    logger: logging.Logger,
    *,
    strategy: str,
    sma: Optional[float] = None,
    z: Optional[float] = None,
    atr_val: Optional[float] = None,
    entry_hour: int = 0,
    extra_log: Optional[Dict[str, Any]] = None,
) -> Optional[OpenPosition]:
    """Enter a position and (live) place a server-side protective stop.

    If live and the protective stop cannot be placed, the position is flattened
    and the entry aborted -- we never hold an unprotected position.
    """
    direction = 1 if side == "BUY" else -1

    fill = ref_price
    stop_order_id: Optional[str] = None
    if not settings.paper_mode:
        result = client.place_order(account_id, contract_id, side, size, "MARKET")
        if result.status != "placed":
            log_event(logger, "strategy.entry_rejected", side=side, raw=result.raw)
            return None
        avg = wait_avg_fill(client, account_id, contract_id)
        fill = avg if avg is not None else ref_price

    stop_price, target_price = stop_target_fn(fill, direction)

    if not settings.paper_mode:
        stop_res = client.place_protective_stop(
            account_id, contract_id, side, size, stop_price
        )
        if stop_res.status != "placed" or stop_res.order_id is None:
            log_event(
                logger, "strategy.protective_stop_failed",
                raw=stop_res.raw, action="flatten_and_abort",
            )
            client.flatten_all(account_id)
            wait_flat(client, account_id, contract_id)
            return None
        stop_order_id = stop_res.order_id

    pos = OpenPosition(
        side=side,
        entry_price=fill,
        size=size,
        stop_price=stop_price,
        target_price=target_price,
        entry_mono=time.monotonic(),
        entry_dt=datetime.now(timezone.utc),
        stop_order_id=stop_order_id,
        sma_at_entry=sma,
        z_at_entry=z,
        atr_at_entry=atr_val,
        entry_hour=entry_hour,
    )
    log_event(
        logger, "strategy.entry",
        strategy=strategy,
        mode="paper" if settings.paper_mode else "live",
        side=side, size=size, fill=fill,
        stop=round(stop_price, 2), target=round(target_price, 2),
        stop_order_id=stop_order_id,
        **(extra_log or {}),
    )
    return pos


def close_position(
    settings: Settings,
    client: TopstepXClient,
    account_id: int,
    contract_id: str,
    pos: OpenPosition,
    price: float,
    reason: str,
    logger: logging.Logger,
    strategy: str,
) -> float:
    """Close the position; return realized P&L in account currency."""
    exit_price = price
    if not settings.paper_mode:
        # Cancel the resting protective stop first so it can't fire after we close.
        if pos.stop_order_id is not None:
            client.cancel_order_safe(account_id, pos.stop_order_id)
        result = client.place_order(
            account_id, contract_id, pos.exit_side, pos.size, "MARKET"
        )
        if result.status != "placed":
            log_event(logger, "strategy.exit_reject_flatten", raw=result.raw)
            client.flatten_all(account_id)
        if not wait_flat(client, account_id, contract_id):
            client.flatten_all(account_id)
            wait_flat(client, account_id, contract_id)

    pv = settings.instrument.point_value
    pnl = (exit_price - pos.entry_price) * pv * pos.size * pos.direction
    log_event(
        logger, "strategy.exit",
        strategy=strategy,
        mode="paper" if settings.paper_mode else "live",
        reason=reason, side=pos.side,
        entry=pos.entry_price, exit=exit_price, pnl=round(pnl, 2),
    )
    return pnl


def journal_trade(
    settings: Settings,
    tz: ZoneInfo,
    contract_id: str,
    pos: OpenPosition,
    exit_price: float,
    reason: str,
    pnl: float,
    strategy: str,
    params: str,
) -> None:
    """Append a closed trade to data/trades.csv (never raises)."""
    try:
        journal_record(TradeRecord(
            session_date=datetime.now(tz).strftime("%Y-%m-%d"),
            entry_time=pos.entry_dt.isoformat(),
            exit_time=datetime.now(timezone.utc).isoformat(),
            mode="paper" if settings.paper_mode else "live",
            strategy=strategy,
            symbol=settings.symbol_root,
            contract_id=contract_id,
            side=pos.side,
            size=pos.size,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            exit_reason=reason,
            pnl=round(pnl, 2),
            hour=pos.entry_hour,
            z_at_entry=round(pos.z_at_entry, 3) if pos.z_at_entry is not None else None,
            sma_at_entry=round(pos.sma_at_entry, 2) if pos.sma_at_entry is not None else None,
            atr_at_entry=round(pos.atr_at_entry, 2) if pos.atr_at_entry is not None else None,
            params=params,
        ))
    except Exception:  # noqa: BLE001 - journaling must never break trading
        pass
