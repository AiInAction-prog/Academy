"""Real-time market data over SignalR (TopstepX / ProjectX market hub).

Connects to ``wss://rtc.topstepx.com/hubs/market`` (live) or the demo RTC hub,
subscribes to contract quotes, and keeps the latest bid/ask/last in memory for
low-latency reads. This is more accurate than deriving price from 1-minute
history bars.

Wiring mirrors the repo's proven scripts (final-trading-bot.py):
    - URL carries the bearer token as ``?access_token=...``
    - on connect, send ``SubscribeContractQuotes [contractId]``
    - event ``GatewayQuote`` delivers ``[contractId, quoteObj]``

Usage::

    stream = SignalRMarketStream(settings, client, contract_id)
    stream.start()
    if stream.wait_for_first_quote(timeout=10):
        print(stream.bid, stream.ask, stream.mid)
    stream.stop()
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

from signalrcore.hub_connection_builder import HubConnectionBuilder

from .broker import TopstepXClient
from .config import Settings


# Field name candidates seen across ProjectX/TopstepX payloads.
_BID_KEYS = ("bestBid", "bidPrice", "bid", "bp")
_ASK_KEYS = ("bestAsk", "askPrice", "ask", "ap")
_LAST_KEYS = ("lastPrice", "close", "price", "last", "c")


def _first(d: Dict[str, Any], keys: tuple[str, ...]) -> Optional[float]:
    for k in keys:
        v = d.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None


class SignalRMarketStream:
    """Thread-safe latest-quote holder fed by the SignalR market hub."""

    def __init__(self, settings: Settings, client: TopstepXClient, contract_id: str):
        self.settings = settings
        self.client = client
        self.contract_id = contract_id

        self._lock = threading.Lock()
        self._bid: Optional[float] = None
        self._ask: Optional[float] = None
        self._last: Optional[float] = None
        self._updated_at: Optional[float] = None  # time.monotonic()

        self._hub = None
        self._first_quote = threading.Event()
        self._running = False

        # Watchdog: restart the hub (with a fresh token) if quotes go stale,
        # so the stream survives the JWT's ~1h expiry over a long session.
        self._monitor: Optional[threading.Thread] = None
        self._stale_after = 90.0       # seconds without a quote -> restart
        self._min_restart_interval = 15.0
        self._last_restart = 0.0

    # -------------------------------------------------------------- lifecycle

    def _build_and_start(self) -> None:
        token = self.client.token()  # auto-refreshes when near expiry
        url = f"{self.settings.market_hub_url}?access_token={token}"
        self._hub = (
            HubConnectionBuilder()
            .with_url(url)
            .with_automatic_reconnect(
                {"type": "raw", "keep_alive_interval": 10, "reconnect_interval": 5}
            )
            .build()
        )
        self._hub.on("GatewayQuote", self._on_quote)
        self._hub.on_open(self._on_open)
        self._hub.on_close(self._on_close)
        self._hub.start()

    def start(self) -> None:
        self._running = True
        self._build_and_start()
        if self._monitor is None or not self._monitor.is_alive():
            self._monitor = threading.Thread(target=self._watchdog, daemon=True)
            self._monitor.start()

    def restart(self) -> None:
        """Tear down and rebuild the hub with a fresh token."""
        self._last_restart = time.monotonic()
        try:
            if self._hub is not None:
                self._hub.stop()
        except Exception:  # noqa: BLE001
            pass
        self._hub = None
        try:
            self._build_and_start()
        except Exception:  # noqa: BLE001 - will retry on next watchdog tick
            self._hub = None

    def _watchdog(self) -> None:
        while self._running:
            time.sleep(10.0)
            if not self._running:
                break
            age = self.age_seconds
            stale = age is None or age > self._stale_after
            cooled = time.monotonic() - self._last_restart > self._min_restart_interval
            if stale and cooled:
                self.restart()

    def stop(self) -> None:
        self._running = False
        if self._hub is not None:
            try:
                self._hub.stop()
            except Exception:  # noqa: BLE001 - shutdown best effort
                pass
            self._hub = None

    def __enter__(self) -> "SignalRMarketStream":
        self.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.stop()

    # ------------------------------------------------------------- callbacks

    def _on_open(self) -> None:
        if self._hub is not None:
            self._hub.send("SubscribeContractQuotes", [self.contract_id])

    def _on_close(self) -> None:
        pass

    def _on_quote(self, args: Any) -> None:
        payload: Any = args
        if isinstance(args, list):
            # GatewayQuote arrives as [contractId, quoteObj]
            payload = args[1] if len(args) == 2 else (args[0] if args else None)
        if not isinstance(payload, dict):
            return

        bid = _first(payload, _BID_KEYS)
        ask = _first(payload, _ASK_KEYS)
        last = _first(payload, _LAST_KEYS)

        with self._lock:
            if bid is not None:
                self._bid = bid
            if ask is not None:
                self._ask = ask
            if last is not None:
                self._last = last
            self._updated_at = time.monotonic()

        if last is not None or (bid is not None and ask is not None):
            self._first_quote.set()

    # ------------------------------------------------------------- accessors

    @property
    def bid(self) -> Optional[float]:
        with self._lock:
            return self._bid

    @property
    def ask(self) -> Optional[float]:
        with self._lock:
            return self._ask

    @property
    def last(self) -> Optional[float]:
        with self._lock:
            return self._last

    @property
    def mid(self) -> Optional[float]:
        with self._lock:
            if self._bid is not None and self._ask is not None:
                return (self._bid + self._ask) / 2.0
            return None

    @property
    def age_seconds(self) -> Optional[float]:
        with self._lock:
            if self._updated_at is None:
                return None
            return time.monotonic() - self._updated_at

    def wait_for_first_quote(self, timeout: float = 10.0) -> bool:
        return self._first_quote.wait(timeout=timeout)
