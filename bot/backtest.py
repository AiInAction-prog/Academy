"""Bar-replay backtester for mean-reversion and VWAP trend strategies.

Reuses the SAME decision logic as the live bot (bot/signals.py).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, time as dtime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence
from zoneinfo import ZoneInfo

from .broker import BrokerError, TopstepXClient
from .config import InstrumentSpec
from .signals import (
    adx,
    atr,
    band_rejection,
    mean_reversion_signal,
    passes_trend_filter,
)

def fetch_history(
    client: TopstepXClient, contract_id: str, days: int, verbose: bool = True
) -> List[Dict[str, Any]]:
    """Pull `days` of 1-min bars in daily chunks, deduped + chronologically sorted.

    Each daily chunk is retried a few times; if a chunk still fails after the
    broker's own HTTP retries it is recorded and reported rather than silently
    dropped. Silently skipping failed chunks (the old behavior) was the cause of
    wildly variable bar counts between runs and untrustworthy backtests.
    """
    end = datetime.now(timezone.utc)
    seen: Dict[Any, Dict[str, Any]] = {}
    failed_chunks = 0
    for d in range(days):
        chunk_end = end - timedelta(days=d)
        chunk_start = chunk_end - timedelta(days=1)
        chunk: List[Dict[str, Any]] = []
        for attempt in range(3):
            try:
                chunk = client.retrieve_bars_between(
                    contract_id, chunk_start, chunk_end,
                    unit=2, unit_number=1, limit=5000,
                )
                break
            except BrokerError:
                if attempt == 2:
                    failed_chunks += 1
                else:
                    time.sleep(0.5 * (attempt + 1))
        for b in chunk:
            key = b.get("t") or b.get("timestamp")
            if key is not None:
                seen[key] = b
    out = list(seen.values())
    out.sort(key=lambda b: str(b.get("t") or b.get("timestamp")))
    if verbose and failed_chunks:
        print(f"  WARNING: {failed_chunks}/{days} daily chunks failed to fetch; "
              f"window is INCOMPLETE - results may be unreliable. Re-run to retry.")
    return out


@dataclass
class BacktestParams:
    lookback: int = 50
    z_entry: float = 2.0
    stop_mode: str = "fixed"      # fixed | atr
    stop_points: float = 25.0
    target_points: float = 30.0
    atr_period: int = 14
    stop_atr_mult: float = 2.0
    target_atr_mult: float = 2.0
    trend_filter: bool = True
    trend_lookback: int = 200
    trend_slope_thresh: float = 0.00002
    allow_long: bool = True
    allow_short: bool = True
    max_hold_bars: int = 0        # 0 = disabled
    session_tz: str = "America/Chicago"
    session_open: str = "08:30"
    session_close: str = "15:00"
    skip_first_minutes: int = 0


@dataclass
class BTTrade:
    entry_time: str
    exit_time: str
    side: str
    entry: float
    exit: float
    reason: str
    pnl: float
    hour: int
    bars_held: int


@dataclass
class BacktestResult:
    trades: List[BTTrade] = field(default_factory=list)
    net_pnl: float = 0.0
    gross_pnl: float = 0.0
    commission_paid: float = 0.0
    wins: int = 0
    losses: int = 0
    max_drawdown: float = 0.0
    by_hour: Dict[int, float] = field(default_factory=dict)
    by_reason: Dict[str, int] = field(default_factory=dict)
    bars: int = 0

    @property
    def n(self) -> int:
        return len(self.trades)

    @property
    def win_rate(self) -> float:
        return self.wins / self.n if self.n else 0.0

    @property
    def expectancy(self) -> float:
        return self.net_pnl / self.n if self.n else 0.0

    @property
    def profit_factor(self) -> float:
        gains = sum(t.pnl for t in self.trades if t.pnl > 0)
        loss = -sum(t.pnl for t in self.trades if t.pnl < 0)
        return gains / loss if loss > 0 else float("inf") if gains > 0 else 0.0

    def summary(self) -> Dict[str, Any]:
        return {
            "trades": self.n,
            "win_rate": round(self.win_rate, 3),
            "net_pnl": round(self.net_pnl, 2),
            "gross_pnl": round(self.gross_pnl, 2),
            "commission": round(self.commission_paid, 2),
            "expectancy_per_trade": round(self.expectancy, 2),
            "profit_factor": round(self.profit_factor, 2),
            "max_drawdown": round(self.max_drawdown, 2),
            "wins": self.wins,
            "losses": self.losses,
            "bars": self.bars,
            "by_reason": self.by_reason,
            "by_hour_pnl": {h: round(v, 2) for h, v in sorted(self.by_hour.items())},
        }


def _bar_time(bar: Dict[str, Any]) -> Optional[datetime]:
    t = bar.get("t") or bar.get("timestamp")
    if t is None:
        return None
    if isinstance(t, (int, float)):
        return datetime.fromtimestamp(t / 1000.0, tz=timezone.utc)
    try:
        return datetime.fromisoformat(str(t).replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_hhmm(text: str) -> dtime:
    hh, mm = text.split(":")
    return dtime(int(hh), int(mm))


def run_backtest(
    bars: Sequence[Dict[str, Any]],
    params: BacktestParams,
    instrument: InstrumentSpec,
    commission_per_side: float = 0.0,
    slippage_ticks: float = 1.0,
) -> BacktestResult:
    """Replay bars and return performance. Bars must be chronological 1-min OHLC."""
    res = BacktestResult(bars=len(bars))
    tz = ZoneInfo(params.session_tz)
    open_t = _parse_hhmm(params.session_open)
    close_t = _parse_hhmm(params.session_close)
    pv = instrument.point_value
    tick = instrument.tick_size
    slip = slippage_ticks * tick

    closes: List[float] = [float(b["c"]) for b in bars]
    times = [_bar_time(b) for b in bars]

    pos: Optional[Dict[str, Any]] = None
    equity = 0.0
    peak = 0.0

    def in_session(dt: Optional[datetime]) -> bool:
        if dt is None:
            return False
        loc = dt.astimezone(tz)
        if loc.weekday() >= 5:
            return False
        return open_t <= loc.time() < close_t

    def mins_since_open(dt: datetime) -> float:
        loc = dt.astimezone(tz)
        o = loc.replace(hour=open_t.hour, minute=open_t.minute, second=0, microsecond=0)
        return (loc - o).total_seconds() / 60.0

    def close_trade(exit_price: float, reason: str, i: int) -> None:
        nonlocal pos, equity, peak
        assert pos is not None
        direction = 1 if pos["side"] == "BUY" else -1
        fill = exit_price - direction * slip   # slippage against us on exit
        gross = (fill - pos["entry"]) * pv * pos["size"] * direction
        total_comm = commission_per_side * pos["size"] * 2   # entry + exit
        pnl = gross - total_comm
        equity += pnl
        peak = max(peak, equity)
        res.max_drawdown = max(res.max_drawdown, peak - equity)
        res.gross_pnl += gross
        res.commission_paid += total_comm
        res.net_pnl += pnl
        if pnl > 0:
            res.wins += 1
        else:
            res.losses += 1
        et = times[i]
        hour = et.astimezone(tz).hour if et else 0
        res.by_hour[hour] = res.by_hour.get(hour, 0.0) + pnl
        res.by_reason[reason] = res.by_reason.get(reason, 0) + 1
        res.trades.append(BTTrade(
            entry_time=pos["entry_time"], exit_time=et.isoformat() if et else "",
            side=pos["side"], entry=pos["entry"], exit=fill, reason=reason,
            pnl=round(pnl, 2),
            hour=pos["entry_hour"], bars_held=i - pos["entry_idx"],
        ))
        pos = None

    n = len(bars)
    for i in range(n):
        dt = times[i]
        bar = bars[i]
        high, low, close = float(bar["h"]), float(bar["l"]), float(bar["c"])

        # Manage an open position on THIS bar.
        if pos is not None:
            direction = 1 if pos["side"] == "BUY" else -1
            # Force flat at/after session close.
            if not in_session(dt):
                close_trade(close, "EOD", i)
            else:
                hit_stop = (low <= pos["stop"]) if direction == 1 else (high >= pos["stop"])
                hit_tgt = (high >= pos["target"]) if direction == 1 else (low <= pos["target"])
                reverted = (
                    close >= pos["sma"] if direction == 1 else close <= pos["sma"]
                )
                bars_held = i - pos["entry_idx"]
                if hit_stop:                       # stop first (conservative)
                    close_trade(pos["stop"], "STOP", i)
                elif hit_tgt:
                    close_trade(pos["target"], "TARGET", i)
                elif reverted:
                    close_trade(close, "SMA_REVERT", i)
                elif params.max_hold_bars and bars_held >= params.max_hold_bars:
                    close_trade(close, "MAX_HOLD", i)

        # Look for a new entry (decided on this bar's close, filled next open).
        if pos is None and i + 1 < n and in_session(dt):
            if params.skip_first_minutes and dt and mins_since_open(dt) < params.skip_first_minutes:
                continue
            window = closes[: i + 1]
            action, sma, z = mean_reversion_signal(window, params.lookback, params.z_entry)
            if action == "BUY" and not params.allow_long:
                action = "HOLD"
            if action == "SELL" and not params.allow_short:
                action = "HOLD"
            if action in ("BUY", "SELL") and params.trend_filter and not passes_trend_filter(
                action, window, params.trend_lookback, params.trend_slope_thresh
            ):
                action = "HOLD"
            if action in ("BUY", "SELL") and sma is not None:
                direction = 1 if action == "BUY" else -1
                entry_open = float(bars[i + 1]["o"]) + direction * slip
                if params.stop_mode == "atr":
                    a = atr(bars[: i + 1], params.atr_period) or params.stop_points
                    stop_dist, tgt_dist = a * params.stop_atr_mult, a * params.target_atr_mult
                else:
                    stop_dist, tgt_dist = params.stop_points, params.target_points
                etime = times[i + 1]
                pos = {
                    "side": action,
                    "entry": entry_open,
                    "size": 1,
                    "stop": entry_open - direction * stop_dist,
                    "target": entry_open + direction * tgt_dist,
                    "sma": sma,
                    "entry_idx": i + 1,
                    "entry_time": etime.isoformat() if etime else "",
                    "entry_hour": etime.astimezone(tz).hour if etime else 0,
                }

    return res


@dataclass
class VwapTrendParams:
    """Strategy 4: VWAP trend-pullback continuation (high frequency).

    The mirror image of the fade family: only trades WITH the trend (ADX high)
    by buying pullbacks to the session VWAP in an uptrend / selling rallies to
    VWAP in a downtrend, with an R-multiple target fixed at entry. Like the
    scalp, there is no per-side-once cap - a side re-arms once ``cooldown_seconds``
    has elapsed, so it can fire many times per session.
    """

    adx_min: float = 25.0               # only trade with-trend when ADX >= this
    target_r: float = 1.5               # take-profit = R multiple of stop risk
    vwap_require_rejection: bool = True  # require the pullback-hold bar at VWAP
    adx_period: int = 14
    vwap_stop_mode: str = "band"        # band | atr
    vwap_stop_buffer: float = 5.0       # points beyond VWAP for the stop (band mode)
    vwap_max_trades: int = 10
    cooldown_seconds: int = 90
    stop_atr_mult: float = 2.0
    skip_first_minutes: int = 0
    allow_long: bool = True
    allow_short: bool = True
    session_tz: str = "America/Chicago"
    session_open: str = "08:30"
    session_close: str = "15:00"


def params_from_settings(settings, strategy: str):
    """Build backtest params for mean_reversion or vwap_trend from live Settings."""
    sc = settings.strategy
    if strategy == "vwap_trend":
        return VwapTrendParams(
            adx_min=sc.vwap_trend_adx_min, target_r=sc.vwap_trend_target_r,
            vwap_require_rejection=sc.vwap_require_rejection,
            adx_period=sc.adx_period, vwap_stop_mode=sc.vwap_stop_mode,
            vwap_stop_buffer=sc.vwap_stop_buffer,
            vwap_max_trades=sc.vwap_trend_max_trades,
            cooldown_seconds=sc.vwap_trend_cooldown_seconds,
            stop_atr_mult=sc.stop_atr_mult, skip_first_minutes=sc.skip_first_minutes,
            allow_long=sc.allow_long, allow_short=sc.allow_short,
            session_tz=sc.session_tz, session_open=sc.session_open,
            session_close=sc.session_close,
        ), run_vwap_trend_backtest
    return BacktestParams(
        lookback=sc.lookback, z_entry=sc.z_entry, stop_mode=sc.stop_mode,
        stop_points=sc.stop_points, target_points=sc.target_points,
        atr_period=sc.atr_period, stop_atr_mult=sc.stop_atr_mult,
        target_atr_mult=sc.target_atr_mult, trend_filter=sc.trend_filter,
        trend_lookback=sc.trend_lookback, trend_slope_thresh=sc.trend_slope_thresh,
        allow_long=sc.allow_long, allow_short=sc.allow_short,
        session_tz=sc.session_tz, session_open=sc.session_open,
        session_close=sc.session_close, skip_first_minutes=sc.skip_first_minutes,
    ), run_backtest

def run_vwap_trend_backtest(
    bars: Sequence[Dict[str, Any]],
    params: VwapTrendParams,
    instrument: InstrumentSpec,
    commission_per_side: float = 0.0,
    slippage_ticks: float = 1.0,
) -> BacktestResult:
    """Replay bars through the VWAP trend-pullback continuation (Strategy 4).

    Mirror image of the fade runners: only trades WITH the trend (ADX >= adx_min)
    by buying pullbacks to VWAP in an uptrend / selling rallies to VWAP in a
    downtrend. Target is a fixed R-multiple of the stop risk (set at entry), not
    a moving VWAP. No per-side cap: a side re-arms once ``cooldown_seconds``
    (converted to whole 1-min bars) has elapsed.
    """
    res = BacktestResult(bars=len(bars))
    tz = ZoneInfo(params.session_tz)
    open_t = _parse_hhmm(params.session_open)
    close_t = _parse_hhmm(params.session_close)
    pv = instrument.point_value
    tick = instrument.tick_size
    slip = slippage_ticks * tick
    cooldown_bars = max(1, round(params.cooldown_seconds / 60.0))

    times = [_bar_time(b) for b in bars]
    pos: Optional[Dict[str, Any]] = None
    equity = 0.0
    peak = 0.0
    cur_day = None
    cpv = cv = cpv2 = 0.0          # running VWAP sums for the session
    day_trades = 0
    last_exit_idx = -10**9         # bar index of the most recent exit (re-arm gate)

    def loc(dt: Optional[datetime]) -> Optional[datetime]:
        return dt.astimezone(tz) if dt else None

    def close_trade(exit_price: float, reason: str, i: int) -> None:
        nonlocal pos, equity, peak, last_exit_idx
        assert pos is not None
        d = 1 if pos["side"] == "BUY" else -1
        fill = exit_price - d * slip
        gross = (fill - pos["entry"]) * pv * pos["size"] * d
        total_comm = commission_per_side * pos["size"] * 2
        pnl = gross - total_comm
        equity += pnl
        peak = max(peak, equity)
        res.max_drawdown = max(res.max_drawdown, peak - equity)
        res.gross_pnl += gross
        res.commission_paid += total_comm
        res.net_pnl += pnl
        if pnl > 0:
            res.wins += 1
        else:
            res.losses += 1
        et = times[i]
        hour = et.astimezone(tz).hour if et else 0
        res.by_hour[hour] = res.by_hour.get(hour, 0.0) + pnl
        res.by_reason[reason] = res.by_reason.get(reason, 0) + 1
        res.trades.append(BTTrade(
            entry_time=pos["entry_time"], exit_time=et.isoformat() if et else "",
            side=pos["side"], entry=pos["entry"], exit=fill, reason=reason,
            pnl=round(pnl, 2), hour=pos["entry_hour"], bars_held=i - pos["entry_idx"],
        ))
        pos = None
        last_exit_idx = i

    n = len(bars)
    for i in range(n):
        dt = times[i]
        lt = loc(dt)
        if lt is None:
            continue
        bar = bars[i]
        high, low, close = float(bar["h"]), float(bar["l"]), float(bar["c"])
        tp = (high + low + close) / 3.0

        if cur_day != lt.date():
            cur_day = lt.date()
            cpv = cv = cpv2 = 0.0
            day_trades = 0
            if pos is not None:
                close_trade(close, "EOD", i)

        in_sess = (lt.weekday() < 5) and (open_t <= lt.time() < close_t)
        if in_sess:
            v = float(bar.get("v", 0) or 0)
            cpv += tp * v
            cv += v
            cpv2 += tp * tp * v

        vwap = None
        if cv > 0:
            vwap = cpv / cv

        # Manage open position (stop priority, then fixed R-multiple target).
        if pos is not None:
            d = 1 if pos["side"] == "BUY" else -1
            if not in_sess:
                close_trade(close, "EOD", i)
            else:
                hit_stop = (low <= pos["stop"]) if d == 1 else (high >= pos["stop"])
                hit_tgt = (high >= pos["target"]) if d == 1 else (low <= pos["target"])
                if hit_stop:
                    close_trade(pos["stop"], "STOP", i)
                elif hit_tgt:
                    close_trade(pos["target"], "TARGET", i)

        # Entry: trade WITH the trend on a pullback to VWAP (no per-side cap).
        if (pos is None and in_sess and vwap is not None and i + 1 < n
                and day_trades < params.vwap_max_trades
                and i - last_exit_idx >= cooldown_bars):
            mins_since_open = (lt - lt.replace(hour=open_t.hour, minute=open_t.minute,
                                               second=0, microsecond=0)).total_seconds() / 60.0
            if params.skip_first_minutes and mins_since_open < params.skip_first_minutes:
                continue
            # Direction from close vs VWAP: above => uptrend (long pullbacks),
            # below => downtrend (short rallies).
            side = None
            if close > vwap and params.allow_long:
                side = "BUY"
            elif close < vwap and params.allow_short:
                side = "SELL"
            if side is not None:
                ok = True
                # Pullback-hold trigger: bar tagged VWAP and closed back on the
                # trend side (band_rejection at the VWAP level).
                if params.vwap_require_rejection:
                    ok = band_rejection(bar, vwap, side)
                if ok:
                    a = adx(bars[: i + 1], params.adx_period)
                    ok = a is not None and a >= params.adx_min
                if ok:
                    d = 1 if side == "BUY" else -1
                    entry = float(bars[i + 1]["o"]) + d * slip
                    if params.vwap_stop_mode == "atr":
                        a_val = atr(bars[: i + 1], params.adx_period) or params.vwap_stop_buffer
                        stop = entry - d * (a_val * params.stop_atr_mult)
                    else:  # band: stop just beyond VWAP on the wrong side
                        stop = vwap - d * params.vwap_stop_buffer
                    risk = (entry - stop) * d
                    if risk > 0:
                        target = entry + d * params.target_r * risk
                        et = times[i + 1]
                        pos = {
                            "side": side, "entry": entry, "size": 1, "stop": stop,
                            "target": target, "entry_idx": i + 1,
                            "entry_time": et.isoformat() if et else "",
                            "entry_hour": et.astimezone(tz).hour if et else 0,
                        }
                        day_trades += 1

    return res

