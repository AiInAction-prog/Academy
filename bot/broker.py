"""TopstepX / ProjectX broker adapter.

Wraps the REST endpoints needed by the bot:

* ``POST /api/Auth/loginKey``      - exchange username + API key for a Bearer JWT
* ``POST /api/Account/search``     - find accounts visible to the API user
* ``POST /api/Contract/search``    - resolve symbol root (MNQ) -> active CONTRACT_ID
* ``POST /api/History/retrieveBars``- recent OHLC bars (used to derive last price)
* ``POST /api/Order/place``        - place an order
* ``POST /api/Order/cancel``       - cancel a working order
* ``POST /api/Order/searchOpen``   - list working (open) orders for an account
* ``POST /api/Position/searchOpen``- list open positions for an account

The token is cached and refreshed proactively ~60s before its 1h TTL expires.

This is intentionally a *thin* HTTP client. Strategy / risk decisions live in
``bot.risk`` and ``bot.main`` - never inside this module.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests

from .config import Settings


TOKEN_TTL_BUFFER_SECONDS = 60


class BrokerError(RuntimeError):
    """Raised when the broker returns a non-2xx response or a success=false payload."""


@dataclass
class Quote:
    contract_id: str
    last: Optional[float]
    bid: Optional[float] = None
    ask: Optional[float] = None
    timestamp: Optional[datetime] = None


@dataclass
class OrderResult:
    order_id: Optional[str]
    status: str
    raw: Dict[str, Any]


class TopstepXClient:
    """Synchronous REST client for the TopstepX (ProjectX gateway) API."""

    def __init__(self, settings: Settings, session: Optional[requests.Session] = None):
        self.settings = settings
        self.base_url = settings.base_url.rstrip("/")
        self.session = session or requests.Session()
        self._token: Optional[str] = None
        self._token_acquired_at: Optional[float] = None
        self._token_ttl: int = 3600

    # ------------------------------------------------------------------ auth

    def authenticate(self) -> str:
        """Force a fresh login and cache the token."""
        url = f"{self.base_url}/api/Auth/loginKey"
        payload = {
            "userName": self.settings.username,
            "apiKey": self.settings.api_key,
        }
        resp = self.session.post(url, json=payload, timeout=15)
        self._raise_for_response(resp, "auth.loginKey")
        data = resp.json()
        token = data.get("token")
        if not data.get("success") or not token:
            raise BrokerError(f"Auth failed: {data}")
        self._token = token
        self._token_acquired_at = time.monotonic()
        self._token_ttl = int(data.get("expiresIn") or 3600)
        return token

    def token(self) -> str:
        if (
            self._token is None
            or self._token_acquired_at is None
            or time.monotonic() - self._token_acquired_at
            > self._token_ttl - TOKEN_TTL_BUFFER_SECONDS
        ):
            self.authenticate()
        assert self._token is not None
        return self._token

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # ----------------------------------------------------------------- HTTP

    # Transient HTTP statuses worth retrying (rate-limit + gateway/server errors).
    _RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
    _MAX_RETRIES = 4

    def _send(
        self,
        method: str,
        path: str,
        *,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Issue an HTTP request with retry + exponential backoff on transient
        failures (timeouts, connection drops, 429/5xx). Non-transient 4xx errors
        raise immediately. This is what makes history fetches deterministic."""
        ctx = f"{method} {path}"
        url = f"{self.base_url}{path}"
        last_exc: Optional[Exception] = None
        for attempt in range(self._MAX_RETRIES):
            try:
                resp = self.session.request(
                    method, url, json=json, params=params,
                    headers=self._headers(), timeout=30,
                )
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_exc = exc
            else:
                if resp.status_code < 400:
                    return resp.json() if resp.content else {}
                if resp.status_code not in self._RETRY_STATUS:
                    self._raise_for_response(resp, ctx)
                last_exc = BrokerError(
                    f"{ctx} -> HTTP {resp.status_code}: {resp.text[:200]}"
                )
                # Honor Retry-After when the server provides it.
                retry_after = resp.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    time.sleep(min(float(retry_after), 10.0))
                    continue
            if attempt < self._MAX_RETRIES - 1:
                time.sleep(min(0.5 * (2 ** attempt), 8.0))
        raise BrokerError(f"{ctx} failed after {self._MAX_RETRIES} attempts: {last_exc}")

    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._send("POST", path, json=payload)

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self._send("GET", path, params=params)

    @staticmethod
    def _raise_for_response(resp: requests.Response, ctx: str) -> None:
        if resp.status_code >= 400:
            raise BrokerError(
                f"{ctx} -> HTTP {resp.status_code}: {resp.text[:500]}"
            )

    # ------------------------------------------------------------- account

    def list_accounts(self, only_active: bool = True) -> List[Dict[str, Any]]:
        data = self._post("/api/Account/search", {"onlyActiveAccounts": only_active})
        return data.get("accounts", [])

    # ------------------------------------------------------------- contract

    def search_contract(self, search_text: str, live_only: bool = False) -> List[Dict[str, Any]]:
        data = self._post(
            "/api/Contract/search",
            {"searchText": search_text, "live": live_only},
        )
        return data.get("contracts", [])

    def resolve_front_month(self, symbol_root: str) -> str:
        """Return the most-active CONTRACT_ID for a root like 'MNQ'.

        Strategy: search by root, prefer entries whose ``activeContract`` flag
        is true, otherwise pick the one with the nearest non-expired
        ``expirationDate``.
        """
        matches = self.search_contract(symbol_root, live_only=False)
        if not matches:
            raise BrokerError(f"No contracts found for symbol root {symbol_root!r}")

        active = [c for c in matches if c.get("activeContract")]
        candidates = active or matches

        now = datetime.now(timezone.utc)
        def expiry_key(c: Dict[str, Any]) -> datetime:
            exp = c.get("expirationDate") or c.get("expiration") or ""
            try:
                dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
            except (TypeError, ValueError):
                return datetime.max.replace(tzinfo=timezone.utc)
            return dt if dt > now else datetime.max.replace(tzinfo=timezone.utc)

        candidates.sort(key=expiry_key)
        chosen = candidates[0]
        contract_id = chosen.get("id") or chosen.get("contractId") or chosen.get("symbol")
        if not contract_id:
            raise BrokerError(f"Could not extract contract id from {chosen!r}")
        return contract_id

    # --------------------------------------------------------------- market

    def retrieve_bars(
        self,
        contract_id: str,
        minutes_back: int = 10,
        unit: int = 2,          # 1=sec, 2=min, 3=hour, 4=day
        unit_number: int = 1,
        limit: int = 10,
        live: bool = False,
    ) -> List[Dict[str, Any]]:
        """Fetch recent OHLC bars via POST /api/History/retrieveBars.

        The TopstepX/ProjectX gateway has no REST ``/quote`` endpoint; last
        price is derived from the most recent bar. Bars come back with keys
        t (time), o, h, l, c, v.
        """
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(minutes=minutes_back)
        payload = {
            "contractId": contract_id,
            "live": live,
            "startTime": start_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "endTime": end_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "unit": unit,
            "unitNumber": unit_number,
            "limit": limit,
            "includePartialBar": True,
        }
        data = self._post("/api/History/retrieveBars", payload)
        if isinstance(data, list):
            return data
        return data.get("bars", [])

    def retrieve_bars_between(
        self,
        contract_id: str,
        start: datetime,
        end: datetime,
        unit: int = 2,
        unit_number: int = 1,
        limit: int = 5000,
        live: bool = False,
    ) -> List[Dict[str, Any]]:
        """Fetch OHLC bars for an explicit [start, end] window (for backtests)."""
        payload = {
            "contractId": contract_id,
            "live": live,
            "startTime": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "endTime": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "unit": unit,
            "unitNumber": unit_number,
            "limit": limit,
            "includePartialBar": False,
        }
        data = self._post("/api/History/retrieveBars", payload)
        if isinstance(data, list):
            return data
        return data.get("bars", [])

    def get_quote(self, contract_id: str) -> Quote:
        """Last price derived from the most recent 1-minute bar.

        Falls back to a wider window if the last 10 minutes are empty (e.g. the
        market just opened or it is a quiet overnight session).
        """
        bars = self.retrieve_bars(contract_id, minutes_back=10)
        if not bars:
            bars = self.retrieve_bars(contract_id, minutes_back=1440, limit=1000)
        last_price = bars[-1].get("c") if bars else None
        return Quote(
            contract_id=contract_id,
            last=last_price,
            bid=None,
            ask=None,
            timestamp=datetime.now(timezone.utc),
        )

    # ---------------------------------------------------------------- orders

    def _round_to_tick(self, price: Optional[float]) -> Optional[float]:
        """Snap a price to the nearest contract tick. Returns None unchanged."""
        if price is None:
            return None
        tick = getattr(self.settings.instrument, "tick_size", 0.0) or 0.0
        if tick <= 0:
            return price
        return round(round(price / tick) * tick, 10)

    def place_order(
        self,
        account_id: int,
        contract_id: str,
        side: str,        # "BUY" or "SELL"
        quantity: int,
        order_type: str = "MARKET",
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None,
    ) -> OrderResult:
        side_code = 0 if side.upper() == "BUY" else 1
        type_map = {"MARKET": 2, "LIMIT": 1, "STOP": 4}
        if order_type.upper() not in type_map:
            raise ValueError(f"Unsupported order_type {order_type!r}")
        # Exchanges reject prices that are not aligned to the contract tick
        # (e.g. NQ = 0.25). Stops/limits are often derived from the bid/ask mid
        # or ATR math and land off-tick, so snap them before sending.
        limit_price = self._round_to_tick(limit_price)
        stop_price = self._round_to_tick(stop_price)
        payload: Dict[str, Any] = {
            "accountId": account_id,
            "contractId": contract_id,
            "type": type_map[order_type.upper()],
            "side": side_code,
            "size": quantity,
            "limitPrice": limit_price,
            "stopPrice": stop_price,
            "trailPrice": None,
            "customTag": None,
            "linkedOrderId": None,
        }
        data = self._post("/api/Order/place", payload)
        return OrderResult(
            order_id=str(data.get("orderId")) if data.get("orderId") is not None else None,
            status="placed" if data.get("success") else "rejected",
            raw=data,
        )

    def place_protective_stop(
        self,
        account_id: int,
        contract_id: str,
        position_side: str,   # side of the OPEN position ("BUY"=long, "SELL"=short)
        size: int,
        stop_price: float,
    ) -> OrderResult:
        """Place a server-side STOP that closes the position if price runs against it.

        For a long position the protective stop is a SELL stop below market; for a
        short it is a BUY stop above market. This order rests at the broker so it
        survives a bot crash / disconnect.
        """
        exit_side = "SELL" if position_side.upper() == "BUY" else "BUY"
        return self.place_order(
            account_id=account_id,
            contract_id=contract_id,
            side=exit_side,
            quantity=size,
            order_type="STOP",
            stop_price=stop_price,
        )

    def cancel_order(self, account_id: int, order_id: str) -> Dict[str, Any]:
        return self._post(
            "/api/Order/cancel",
            {"accountId": account_id, "orderId": int(order_id)},
        )

    def cancel_order_safe(self, account_id: int, order_id: str) -> bool:
        """Cancel without raising; returns True on success."""
        try:
            self.cancel_order(account_id, order_id)
            return True
        except BrokerError:
            return False

    def search_open_orders(self, account_id: int) -> List[Dict[str, Any]]:
        """List working (open/pending) orders for an account."""
        data = self._post("/api/Order/searchOpen", {"accountId": account_id})
        return data.get("orders", [])

    def list_open_positions(self, account_id: int) -> List[Dict[str, Any]]:
        data = self._post("/api/Position/searchOpen", {"accountId": account_id})
        return data.get("positions", [])

    def close_position(self, account_id: int, contract_id: str) -> Dict[str, Any]:
        return self._post(
            "/api/Position/closeContract",
            {"accountId": account_id, "contractId": contract_id},
        )

    def flatten_all(self, account_id: int) -> List[Dict[str, Any]]:
        """Close every open position on the account. Used by the kill switch."""
        results = []
        for pos in self.list_open_positions(account_id):
            cid = pos.get("contractId") or pos.get("contract_id")
            if not cid:
                continue
            try:
                results.append(self.close_position(account_id, cid))
            except BrokerError as exc:
                results.append({"error": str(exc), "contractId": cid})
        return results
