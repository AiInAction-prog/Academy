"""Shared signal + indicator functions.

This module is the single source of truth for the entry signal and filters, so
the live bot (bot/strategy.py) and the backtester (bot/backtest.py) run IDENTICAL
logic. Keep all decision math here; keep execution/plumbing out.

Bars are dicts with keys o, h, l, c (and optionally v) as returned by
TopstepXClient.retrieve_bars.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np


# --------------------------------------------------------------- entry signal


def mean_reversion_signal(
    closes: Sequence[float], lookback: int, z_entry: float
) -> Tuple[str, Optional[float], Optional[float]]:
    """Return (action, sma, z). action in {BUY, SELL, HOLD}.

    LONG when oversold (z <= -z_entry), SHORT when overbought (z >= z_entry).
    """
    if len(closes) < lookback:
        return "HOLD", None, None
    window = np.asarray(closes[-lookback:], dtype=float)
    sma = float(window.mean())
    std = float(window.std())
    price = float(closes[-1])
    if std <= 0:
        return "HOLD", sma, None
    z = (price - sma) / std
    if z <= -z_entry:
        return "BUY", sma, z
    if z >= z_entry:
        return "SELL", sma, z
    return "HOLD", sma, z


# ------------------------------------------------------------------ indicators


def atr(bars: Sequence[Dict[str, float]], period: int = 14) -> Optional[float]:
    """Average True Range over the last ``period`` bars (in price points)."""
    if len(bars) < period + 1:
        return None
    trs: List[float] = []
    for i in range(1, len(bars)):
        h = float(bars[i]["h"])
        low = float(bars[i]["l"])
        prev_close = float(bars[i - 1]["c"])
        tr = max(h - low, abs(h - prev_close), abs(low - prev_close))
        trs.append(tr)
    if len(trs) < period:
        return None
    return float(np.mean(trs[-period:]))


def trend_state(closes: Sequence[float], lookback: int) -> Optional[float]:
    """Normalized slope of a long SMA window.

    Returns slope per bar divided by the window mean (so it's scale-free, ~ the
    fractional drift per bar). Positive = uptrend, negative = downtrend.
    None if not enough data.
    """
    if len(closes) < lookback:
        return None
    window = np.asarray(closes[-lookback:], dtype=float)
    x = np.arange(len(window), dtype=float)
    # least-squares slope
    slope = float(np.polyfit(x, window, 1)[0])
    mean = float(window.mean())
    if mean == 0:
        return None
    return slope / mean


def passes_trend_filter(
    side: str,
    closes: Sequence[float],
    lookback: int,
    slope_thresh: float,
) -> bool:
    """Block fading a strong trend.

    Don't go LONG (mean-revert up) when the long trend is strongly DOWN, and
    don't go SHORT when the long trend is strongly UP. ``slope_thresh`` is the
    normalized per-bar slope magnitude above which a trend is "strong".
    If there isn't enough data to judge, allow the trade (return True).
    """
    slope = trend_state(closes, lookback)
    if slope is None:
        return True
    if side == "BUY" and slope <= -abs(slope_thresh):
        return False
    if side == "SELL" and slope >= abs(slope_thresh):
        return False
    return True


# ------------------------------------------------------- VWAP (trend pullback)


def session_vwap_bands(
    session_bars: Sequence[Dict[str, float]], num_std: float = 2.0
) -> Optional[Tuple[float, float, float, float]]:
    """Return (vwap, upper, lower, std) from this session's bars so far.

    VWAP = sum(typical_price * volume) / sum(volume), typical = (h+l+c)/3.
    std  = volume-weighted std of typical price around VWAP.
    Bands = vwap +/- num_std * std. None if no/zero volume.
    """
    if not session_bars:
        return None
    tp = np.array([(float(b["h"]) + float(b["l"]) + float(b["c"])) / 3.0
                   for b in session_bars], dtype=float)
    vol = np.array([float(b.get("v", 0) or 0) for b in session_bars], dtype=float)
    vsum = float(vol.sum())
    if vsum <= 0:
        return None
    vwap = float((tp * vol).sum() / vsum)
    var = float((vol * (tp - vwap) ** 2).sum() / vsum)
    std = var ** 0.5
    return vwap, vwap + num_std * std, vwap - num_std * std, std


def band_rejection(bar: Dict[str, float], level: float, side: str) -> bool:
    """Wick-rejection trigger at a band.

    SHORT (fade upper band): bar poked above the band (high >= level) but closed
    back below it. LONG (fade lower band): low <= level but close back above it.
    """
    high, low, close = float(bar["h"]), float(bar["l"]), float(bar["c"])
    if side == "SELL":
        return high >= level and close < level
    return low <= level and close > level


def adx(bars: Sequence[Dict[str, float]], period: int = 14) -> Optional[float]:
    """ADX (trend strength) via SMA-smoothed DI+/DI-. High = trending.

    Used as a regime filter: only fade (mean-revert) when ADX is low (range).
    None if insufficient data.
    """
    if len(bars) < 2 * period + 1:
        return None
    highs = [float(b["h"]) for b in bars]
    lows = [float(b["l"]) for b in bars]
    closes = [float(b["c"]) for b in bars]

    trs: List[float] = []
    plus_dm: List[float] = []
    minus_dm: List[float] = []
    for i in range(1, len(bars)):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        plus_dm.append(up if (up > down and up > 0) else 0.0)
        minus_dm.append(down if (down > up and down > 0) else 0.0)
        trs.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]),
                       abs(lows[i] - closes[i - 1])))

    tr_arr = np.asarray(trs, dtype=float)
    pdm = np.asarray(plus_dm, dtype=float)
    mdm = np.asarray(minus_dm, dtype=float)

    dx: List[float] = []
    for i in range(period, len(tr_arr) + 1):
        tr_sum = tr_arr[i - period:i].sum()
        if tr_sum <= 0:
            continue
        pdi = 100.0 * pdm[i - period:i].sum() / tr_sum
        mdi = 100.0 * mdm[i - period:i].sum() / tr_sum
        denom = pdi + mdi
        if denom <= 0:
            dx.append(0.0)
        else:
            dx.append(100.0 * abs(pdi - mdi) / denom)
    if len(dx) < period:
        return None
    return float(np.mean(dx[-period:]))
