#!/usr/bin/env python3
"""
Discover accounts: list every account your API key can see, and mark the one
the course code is allowed to use, your TopStep Practice account.

Your API key is sent to TopstepX to log in and is never printed.
"""

import os
import sys

import requests
from dotenv import load_dotenv

from bot.practice_guard import BANNER, PRACTICE_PREFIX, is_practice_account

# Avoid UnicodeEncodeError on Windows consoles (cp1252).
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

load_dotenv()

BASE_URL = "https://api.topstepx.com"


def authenticate(username, api_key):
    """Return a session token, or None. Never prints the key or the token."""
    try:
        response = requests.post(
            f"{BASE_URL}/api/Auth/loginKey",
            json={"userName": username, "apiKey": api_key},
            timeout=15,
        )
    except requests.RequestException as exc:
        print(f"[AUTH] Could not reach TopstepX: {type(exc).__name__}")
        return None
    if response.status_code != 200:
        print(f"[AUTH] Login failed: HTTP {response.status_code}")
        return None
    data = response.json()
    token = data.get("token")
    if not data.get("success") or not token:
        print(f"[AUTH] Login failed: {data.get('errorMessage') or 'no token returned'}")
        return None
    return token


def get_accounts(token):
    response = requests.post(
        f"{BASE_URL}/api/Account/search",
        headers={"Authorization": f"Bearer {token}"},
        json={"onlyActiveAccounts": True},
        timeout=15,
    )
    if response.status_code != 200:
        print(f"Account search failed: HTTP {response.status_code}")
        return []
    return response.json().get("accounts", [])


def main():
    print(BANNER)
    print()

    username = (os.getenv("TSX_USERNAME") or "").strip()
    api_key = (os.getenv("API_KEY") or "").strip()
    if not username or not api_key:
        print("Missing TSX_USERNAME or API_KEY in .env.")
        print("Open .env, paste your TopstepX login username and API key, then re-run:")
        print("  .\\.venv\\Scripts\\python.exe discover-accounts.py")
        sys.exit(1)

    token = authenticate(username, api_key)
    if not token:
        sys.exit(1)

    accounts = get_accounts(token)
    print(f"{len(accounts)} account(s) found")
    practice = []
    for account in accounts:
        name = account.get("name", "Unknown")
        if is_practice_account(account):
            practice.append(account)
            print(f"  {name:<28} id {account.get('id')}   practice   use this one")
        else:
            print(f"  {name:<28} skipped: not a Practice account")
    print()

    if not practice:
        print(f"No Practice account found (names start with {PRACTICE_PREFIX}).")
        print("Activate the free TopstepX Practice account in the Topstep dashboard")
        print("(Accounts > Add Ons), then run this again.")
        sys.exit(1)

    print("Next steps:")
    print(f"  1. Set ACCOUNT_ID={practice[0].get('id')} in .env")
    print("  2. Smoke test: .\\.venv\\Scripts\\python.exe run_bot.py --check")
    print("  3. Keep PAPER_MODE=true until you start your first session")
    print()
    print("The bot refuses to trade on any account that isn't your Practice account.")


if __name__ == "__main__":
    main()
