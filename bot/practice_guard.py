"""Practice-account-only guard.

This code is course material for the AI in Action course. It may only trade
on a TopStep Practice account, never on a Combine evaluation, funded,
real-money, brokerage or retirement account.

One TopstepX API key reaches every eligible account on your profile, so the
key alone says nothing about which account an order lands on. The ProjectX
``Account/search`` response has no account-type field, and Combine accounts
report ``simulated`` just like Practice accounts do. The only reliable marker
is the account name: TopstepX names Practice accounts with a ``PRAC`` prefix
(for example ``PRAC-V2-...``). Anything else is refused.
"""

from __future__ import annotations

from typing import Any, Iterable, List, Mapping

BANNER = "PRACTICE ACCOUNT ONLY. Not trading advice."
PRACTICE_PREFIX = "PRAC"


class PracticeAccountError(RuntimeError):
    """Raised when an account can't be confirmed as a TopStep Practice account."""


def is_practice_account(account: Mapping[str, Any]) -> bool:
    name = str(account.get("name") or "").strip().upper()
    return name.startswith(PRACTICE_PREFIX)


def practice_accounts(accounts: Iterable[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
    return [a for a in accounts if is_practice_account(a)]


def require_practice_account(
    accounts: Iterable[Mapping[str, Any]], account_id: int
) -> Mapping[str, Any]:
    """Return the account with ``account_id`` if it is a tradable Practice account.

    Raises ``PracticeAccountError`` otherwise, including when the account isn't
    in the list at all: an account we can't see is an account we can't confirm.
    """
    for account in accounts:
        if str(account.get("id")) != str(account_id):
            continue
        name = account.get("name")
        if not is_practice_account(account):
            raise PracticeAccountError(
                f"Account {account_id} ({name!r}) is not a TopStep Practice account. "
                f"This code only trades on your Practice account, whose name starts "
                f"with {PRACTICE_PREFIX}. Run discover-accounts.py to find it."
            )
        if account.get("canTrade") is False:
            raise PracticeAccountError(
                f"Practice account {account_id} ({name!r}) can't trade right now "
                f"(canTrade is false). Check it in TopstepX."
            )
        return account
    raise PracticeAccountError(
        f"Account {account_id} isn't an active account visible to this API key, "
        f"so it can't be confirmed as a Practice account. Run discover-accounts.py."
    )
