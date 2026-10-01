"""Trade journal: append every closed trade to data/trades.csv.

The journal is the raw material for learning from past sessions
(tools/analyze_sessions.py). It is intentionally a flat, human-readable CSV so
you can open it in Excel or pandas. data/ is gitignored.
"""

from __future__ import annotations

import csv
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_JOURNAL_PATH = REPO_ROOT / "data" / "trades.csv"
# Back-compat alias; prefer ``journal_path()`` so a per-process override is honored.
JOURNAL_PATH = DEFAULT_JOURNAL_PATH


def journal_path() -> Path:
    """Resolve the trade-journal CSV path.

    Honors the ``JOURNAL_FILE`` env var so multiple bot processes (e.g. one per
    account/strategy) can each write an isolated journal. A relative value is
    resolved against the repo root. Falls back to ``data/trades.csv``.
    """
    override = os.getenv("JOURNAL_FILE", "").strip()
    if not override:
        return DEFAULT_JOURNAL_PATH
    path = Path(override)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path

FIELDS = [
    "session_date",
    "entry_time",
    "exit_time",
    "mode",            # paper | live
    "strategy",        # mean_reversion | ttm_orb
    "symbol",
    "contract_id",
    "side",            # BUY | SELL
    "size",
    "entry_price",
    "exit_price",
    "exit_reason",     # STOP | TARGET | SMA_REVERT | EOD | HALT | SHUTDOWN | SERVER_STOP | OR_*
    "pnl",
    "hour",            # hour-of-day (session tz) at entry
    "z_at_entry",
    "sma_at_entry",
    "atr_at_entry",
    "params",          # compact snapshot of key strategy params
]


@dataclass
class TradeRecord:
    session_date: str
    entry_time: str
    exit_time: str
    mode: str
    symbol: str
    contract_id: str
    side: str
    size: int
    entry_price: float
    exit_price: float
    exit_reason: str
    pnl: float
    hour: int
    strategy: str = "mean_reversion"
    z_at_entry: Optional[float] = None
    sma_at_entry: Optional[float] = None
    atr_at_entry: Optional[float] = None
    params: str = ""


def record_trade(rec: TradeRecord) -> None:
    """Append a trade row, creating the file + header on first write."""
    path = journal_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists()
    row = {k: v for k, v in asdict(rec).items() if k in FIELDS}
    try:
        with path.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=FIELDS)
            if new_file:
                writer.writeheader()
            writer.writerow(row)
    except OSError:
        # Journaling must never break trading.
        pass


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
