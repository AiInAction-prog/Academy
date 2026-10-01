"""Risk controls for the bot.

Three layers that any signal must pass before reaching the broker:

1. **Static caps**: max contracts per trade, max trades per day,
   max consecutive losses.
2. **Account guardrails**: daily realized-loss limit and trailing maximum
   drawdown (Topstep style). When tripped, the bot flattens via the broker's
   ``flatten_all`` and refuses to open new positions for the rest of the day.
3. **Kill switch**: a sentinel file ``KILL_SWITCH`` in the repo root. If
   present, the bot flattens immediately and exits. Touch the file to halt the
   bot from outside (e.g. from another terminal or a hotkey script).

Session state lives in-memory only; restarting the bot resets the day counters,
so ``RiskGate.start_new_session`` should be called once per logical trading day.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import List, Optional

from .config import RiskCaps, Settings
from .logger import log_event


KILL_SWITCH_FILE = "KILL_SWITCH"


@dataclass
class TradeOutcome:
    """One closed trade's P&L in account currency."""
    pnl: float
    closed_at: datetime
    contract_id: str
    size: int


@dataclass
class SessionState:
    started_on: date
    realized_pnl: float = 0.0
    peak_equity: float = 0.0          # high-water mark of starting_equity + realized_pnl
    starting_equity: float = 0.0
    trades_today: int = 0
    consecutive_losses: int = 0
    halted_reason: Optional[str] = None
    closed_trades: List[TradeOutcome] = field(default_factory=list)

    @property
    def equity(self) -> float:
        return self.starting_equity + self.realized_pnl

    @property
    def trailing_drawdown(self) -> float:
        """How far below the high-water mark the account currently is."""
        return max(0.0, self.peak_equity - self.equity)


class HaltError(RuntimeError):
    """Raised when the bot refuses to open a new position due to risk rules."""


class RiskGate:
    """Single gateway every order must pass through."""

    def __init__(
        self,
        settings: Settings,
        logger: logging.Logger,
        starting_equity: float = 0.0,
    ):
        self.settings = settings
        self.caps: RiskCaps = settings.risk
        self.logger = logger
        self.kill_switch_path = Path(__file__).resolve().parent.parent / KILL_SWITCH_FILE
        self.state = SessionState(
            started_on=datetime.now(timezone.utc).date(),
            starting_equity=starting_equity,
            peak_equity=starting_equity,
        )

    # ------------------------------------------------------------ lifecycle

    def start_new_session(self, starting_equity: float) -> None:
        self.state = SessionState(
            started_on=datetime.now(timezone.utc).date(),
            starting_equity=starting_equity,
            peak_equity=starting_equity,
        )
        log_event(
            self.logger,
            "risk.session_started",
            equity=starting_equity,
            caps={
                "daily_loss_limit": self.caps.daily_loss_limit,
                "trailing_drawdown": self.caps.trailing_drawdown,
                "max_contracts_per_trade": self.caps.max_contracts_per_trade,
                "max_trades_per_day": self.caps.max_trades_per_day,
                "max_consecutive_losses": self.caps.max_consecutive_losses,
            },
        )

    # --------------------------------------------------------- kill switch

    def kill_switch_tripped(self) -> bool:
        return self.kill_switch_path.exists()

    def arm_kill_switch_message(self) -> str:
        return (
            f"Kill switch armed: create file {self.kill_switch_path} to flatten "
            f"and halt. Delete it to re-enable trading."
        )

    # ---------------------------------------------------- check before open

    def check_can_open(self, size: int) -> None:
        """Raise ``HaltError`` if a new entry would violate any rule."""
        if self.state.halted_reason:
            raise HaltError(self.state.halted_reason)

        if self.kill_switch_tripped():
            self._halt("kill_switch_file_present")
            raise HaltError("Kill switch file present")

        if size <= 0:
            raise HaltError(f"Invalid size {size}")

        if size > self.caps.max_contracts_per_trade:
            raise HaltError(
                f"Requested size {size} exceeds MAX_CONTRACTS_PER_TRADE="
                f"{self.caps.max_contracts_per_trade}"
            )

        if self.state.trades_today >= self.caps.max_trades_per_day:
            self._halt("max_trades_per_day_reached")
            raise HaltError("Max trades per day reached")

        if self.state.consecutive_losses >= self.caps.max_consecutive_losses:
            self._halt("max_consecutive_losses_reached")
            raise HaltError("Max consecutive losses reached")

        if -self.state.realized_pnl >= self.caps.daily_loss_limit:
            self._halt("daily_loss_limit_breached")
            raise HaltError("Daily loss limit breached")

        if self.state.trailing_drawdown >= self.caps.trailing_drawdown:
            self._halt("trailing_drawdown_breached")
            raise HaltError("Trailing drawdown breached")

        if (self.caps.min_account_equity > 0
                and self.state.equity <= self.caps.min_account_equity):
            self._halt("account_min_equity_breached")
            raise HaltError("Account minimum-equity floor breached")

    # --------------------------------------------------- record trade close

    def record_trade(self, outcome: TradeOutcome) -> None:
        self.state.closed_trades.append(outcome)
        self.state.realized_pnl += outcome.pnl
        self.state.trades_today += 1
        if outcome.pnl < 0:
            self.state.consecutive_losses += 1
        else:
            self.state.consecutive_losses = 0
        if self.state.equity > self.state.peak_equity:
            self.state.peak_equity = self.state.equity

        log_event(
            self.logger,
            "risk.trade_recorded",
            pnl=outcome.pnl,
            realized_pnl_day=self.state.realized_pnl,
            equity=self.state.equity,
            trailing_dd=self.state.trailing_drawdown,
            trades_today=self.state.trades_today,
            consecutive_losses=self.state.consecutive_losses,
            contract_id=outcome.contract_id,
            size=outcome.size,
        )

        # Eagerly halt if a closing fill breached anything, so the *next*
        # check_can_open doesn't need to fail to mark the bot halted.
        if (self.caps.min_account_equity > 0
                and self.state.equity <= self.caps.min_account_equity):
            self._halt("account_min_equity_breached")
        elif -self.state.realized_pnl >= self.caps.daily_loss_limit:
            self._halt("daily_loss_limit_breached")
        elif self.state.trailing_drawdown >= self.caps.trailing_drawdown:
            self._halt("trailing_drawdown_breached")
        elif self.state.consecutive_losses >= self.caps.max_consecutive_losses:
            self._halt("max_consecutive_losses_reached")
        elif (
            self.caps.daily_profit_target > 0
            and self.state.realized_pnl >= self.caps.daily_profit_target
        ):
            self._halt("daily_profit_target_reached")

    def reconcile_realized(self, actual_realized_pnl: float) -> None:
        """Override the day's realized P&L with an authoritative value.

        The per-trade P&L recorded during the session is estimated from mid
        prices and can drift from real fills/fees. Call this with
        (current_account_balance - session_starting_balance) while flat to keep
        the daily-loss / trailing-drawdown guardrails honest, and halt if a cap
        is now breached.
        """
        self.state.realized_pnl = actual_realized_pnl
        if self.state.equity > self.state.peak_equity:
            self.state.peak_equity = self.state.equity

        log_event(
            self.logger,
            "risk.reconciled",
            realized_pnl_day=self.state.realized_pnl,
            equity=self.state.equity,
            trailing_dd=self.state.trailing_drawdown,
        )

        if (self.caps.min_account_equity > 0
                and self.state.equity <= self.caps.min_account_equity):
            self._halt("account_min_equity_breached")
        elif -self.state.realized_pnl >= self.caps.daily_loss_limit:
            self._halt("daily_loss_limit_breached")
        elif self.state.trailing_drawdown >= self.caps.trailing_drawdown:
            self._halt("trailing_drawdown_breached")
        elif (
            self.caps.daily_profit_target > 0
            and self.state.realized_pnl >= self.caps.daily_profit_target
        ):
            self._halt("daily_profit_target_reached")

    # -------------------------------------------------------------- helpers

    def _halt(self, reason: str) -> None:
        if self.state.halted_reason:
            return
        self.state.halted_reason = reason
        log_event(
            self.logger,
            "risk.halt",
            reason=reason,
            realized_pnl_day=self.state.realized_pnl,
            equity=self.state.equity,
            trailing_dd=self.state.trailing_drawdown,
        )

    def is_halted(self) -> bool:
        return self.state.halted_reason is not None
