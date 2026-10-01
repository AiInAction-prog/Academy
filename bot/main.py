"""TopstepX futures bot entry point.

Invocation:

    python run_bot.py                  # paper mode, resolve front month
    python run_bot.py --check          # auth + quote only, no loop
    python run_bot.py --flatten        # close all open positions and exit
"""

from __future__ import annotations

import argparse
import importlib
import sys
from typing import Callable, Optional

from .broker import BrokerError, TopstepXClient
from .config import Settings, load_settings
from .logger import get_logger, log_event
from .marketstream import SignalRMarketStream
from .pricing import live_price
from .risk import RiskGate
from .singleton import SingleInstance, SingleInstanceError

_STRATEGY_MODULES = {
    "mean_reversion": "bot.strategy",
    "vwap_trend": "bot.strategy_vwap_trend",
}


LIVE_CONFIRM_PHRASE = "I UNDERSTAND"


def _confirm_live_mode() -> None:
    print()
    print("=" * 64)
    print(" LIVE TRADING MODE: real money, real orders will be placed.")
    print(f" Type exactly  {LIVE_CONFIRM_PHRASE!r}  to continue, anything else aborts.")
    print("=" * 64)
    try:
        reply = input("> ").strip()
    except (EOFError, KeyboardInterrupt):
        reply = ""
    if reply != LIVE_CONFIRM_PHRASE:
        print("Aborted.")
        sys.exit(2)


def _resolve_account(client: TopstepXClient, settings: Settings) -> int:
    if settings.account_id is not None:
        return settings.account_id
    accounts = client.list_accounts(only_active=True)
    if not accounts:
        raise SystemExit(
            "No active accounts visible to this API key. Set ACCOUNT_ID in .env."
        )
    if len(accounts) > 1:
        labels = ", ".join(
            f"{a.get('id')}={a.get('name')!r}" for a in accounts
        )
        raise SystemExit(
            f"Multiple accounts visible: {labels}. Set ACCOUNT_ID in .env to pick one."
        )
    return int(accounts[0]["id"])


def _resolve_contract(client: TopstepXClient, settings: Settings) -> str:
    if settings.contract_id:
        return settings.contract_id
    return client.resolve_front_month(settings.symbol_root)


def _load_strategy_runner(name: str) -> Callable:
    module_path = _STRATEGY_MODULES.get(name)
    if module_path is None:
        raise KeyError(name)
    module = importlib.import_module(module_path)
    return module.run


def _strategy_loop(
    settings: Settings,
    client: TopstepXClient,
    gate: RiskGate,
    account_id: int,
    contract_id: str,
    stream: "Optional[SignalRMarketStream]" = None,
    max_runtime_s: Optional[float] = None,
) -> None:
    try:
        runner = _load_strategy_runner(settings.strategy.name)
    except KeyError:
        log_event(
            gate.logger,
            "strategy.unknown",
            name=settings.strategy.name,
            supported=sorted(_STRATEGY_MODULES),
            message="No runner for this STRATEGY value; nothing to do.",
        )
        return
    runner(
        settings, client, gate, account_id, contract_id, stream,
        gate.logger, max_runtime_s=max_runtime_s,
    )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="2nd-trader")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Authenticate and fetch a quote only. Do not start the strategy loop.",
    )
    parser.add_argument(
        "--flatten",
        action="store_true",
        help="Close all open positions on the configured account and exit.",
    )
    parser.add_argument(
        "--non-interactive",
        "--yes",
        dest="non_interactive",
        action="store_true",
        help="Skip the live-mode confirmation prompt (for unattended runs).",
    )
    parser.add_argument(
        "--max-runtime",
        dest="max_runtime",
        type=float,
        default=None,
        help="Stop the strategy loop after this many seconds (for smoke tests).",
    )
    args = parser.parse_args(argv)

    settings = load_settings()
    logger = get_logger("bot", settings.log_dir, settings.log_level)

    log_event(
        logger,
        "bot.starting",
        env=settings.env,
        paper_mode=settings.paper_mode,
        symbol_root=settings.symbol_root,
        contract_id=settings.contract_id,
        account_id=settings.account_id,
    )

    if not settings.paper_mode:
        if args.non_interactive:
            log_event(
                logger,
                "bot.live_armed_noninteractive",
                message="PAPER_MODE=false with --non-interactive: live orders armed.",
            )
            print("WARNING: live (sim) orders armed via --non-interactive.")
        else:
            _confirm_live_mode()

    client = TopstepXClient(settings)

    try:
        client.authenticate()
        log_event(logger, "broker.authenticated", env=settings.env, base=settings.base_url)

        account_id = _resolve_account(client, settings)
        log_event(logger, "broker.account_resolved", account_id=account_id)

        if args.flatten:
            results = client.flatten_all(account_id)
            log_event(logger, "broker.flatten_all", count=len(results), results=results)
            print(f"Flattened {len(results)} position(s).")
            return 0

        contract_id = _resolve_contract(client, settings)
        log_event(
            logger,
            "broker.contract_resolved",
            symbol_root=settings.symbol_root,
            contract_id=contract_id,
        )

        spec = settings.instrument
        quote = client.get_quote(contract_id)
        log_event(
            logger,
            "broker.quote",
            contract_id=contract_id,
            last=quote.last,
            bid=quote.bid,
            ask=quote.ask,
        )

        # Real-time price via SignalR (falls back to REST bars if unavailable).
        stream: Optional[SignalRMarketStream] = None
        pq = None
        try:
            stream = SignalRMarketStream(settings, client, contract_id)
            stream.start()
            if stream.wait_for_first_quote(timeout=10):
                pq = live_price(stream, client, contract_id)
                log_event(
                    logger,
                    "stream.first_quote",
                    bid=stream.bid,
                    ask=stream.ask,
                    mid=stream.mid,
                    source=pq.source,
                )
            else:
                log_event(logger, "stream.no_quote_timeout")
        except Exception as exc:  # noqa: BLE001 - stream is best-effort
            log_event(logger, "stream.error", error=str(exc), type=type(exc).__name__)

        print()
        print(f"  Environment : {settings.env}  ({settings.base_url})")
        print(f"  Account     : {account_id}")
        print(f"  Symbol      : {settings.symbol_root}  ({spec.description})")
        print(f"  Contract    : {contract_id}")
        print(f"  Last (bars) : {quote.last}")
        if stream is not None and stream.age_seconds is not None:
            print(f"  Live quote  : bid={stream.bid} ask={stream.ask} mid={stream.mid}")
            if pq is not None:
                print(f"  Price source: {pq.source} -> {pq.price}")
        else:
            print("  Live quote  : (stream unavailable; using REST bars)")
        print(f"  Tick / point: {spec.tick_size} pts, ${spec.tick_value} per tick")
        print(f"  Paper mode  : {settings.paper_mode}")
        print(f"  Caps        : day_loss=${settings.risk.daily_loss_limit:.0f}, "
              f"trail_dd=${settings.risk.trailing_drawdown:.0f}, "
              f"max_contracts={settings.risk.max_contracts_per_trade}")
        print()

        gate = RiskGate(settings, logger, starting_equity=0.0)
        print(gate.arm_kill_switch_message())

        if args.check:
            log_event(logger, "bot.check_complete")
            if stream is not None:
                stream.stop()
            return 0

        # Single-instance guard: refuse to start if another live bot is already
        # running against this account. Prevents orphaned/duplicate instances
        # from double-trading (and doubling losses). The OS releases the lock
        # automatically if a holder crashes, so stale locks self-heal.
        instance_lock: Optional[SingleInstance] = None
        if not settings.paper_mode:
            instance_lock = SingleInstance(f"acct_{account_id}")
            try:
                instance_lock.acquire()
            except SingleInstanceError:
                log_event(logger, "bot.already_running", account_id=account_id)
                print(
                    f"ERROR: another bot instance is already trading account "
                    f"{account_id}. Refusing to start a second one.",
                    file=sys.stderr,
                )
                if stream is not None:
                    stream.stop()
                return 3

        try:
            _strategy_loop(
                settings, client, gate, account_id, contract_id, stream,
                max_runtime_s=args.max_runtime,
            )
        finally:
            if stream is not None:
                stream.stop()
            if instance_lock is not None:
                instance_lock.release()
        return 0

    except BrokerError as exc:
        log_event(logger, "broker.error", error=str(exc))
        print(f"BrokerError: {exc}", file=sys.stderr)
        return 1
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        log_event(logger, "bot.fatal", error=str(exc), type=type(exc).__name__)
        print(f"Fatal: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
