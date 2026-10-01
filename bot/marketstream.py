"""Unified price source: prefer live SignalR, fall back to REST bars.

Priority:
1. SignalR stream mid ((bid+ask)/2) if the stream is fresh and has a book.
2. SignalR stream last trade if fresh but no book.
3. REST ``retrieveBars`` last close (``client.get_quote``) otherwise.

Returns a ``PriceQuote`` so callers can see which source was used.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .broker import TopstepXClient
from .marketstream import SignalRMarketStream


@dataclass
class PriceQuote:
    price: Optional[float]
    source: str           # "stream_mid" | "stream_last" | "rest_bars" | "none"
    bid: Optional[float] = None
    ask: Optional[float] = None


def live_price(
    stream: Optional[SignalRMarketStream],
    client: TopstepXClient,
    contract_id: str,
    max_age: float = 5.0,
) -> PriceQuote:
    """Best available price, preferring the live stream when fresh."""
    if stream is not None:
        age = stream.age_seconds
        if age is not None and age <= max_age:
            mid = stream.mid
            if mid is not None:
                return PriceQuote(mid, "stream_mid", stream.bid, stream.ask)
            last = stream.last
            if last is not None:
                return PriceQuote(last, "stream_last", stream.bid, stream.ask)

    quote = client.get_quote(contract_id)
    if quote.last is not None:
        return PriceQuote(quote.last, "rest_bars")
    return PriceQuote(None, "none")
