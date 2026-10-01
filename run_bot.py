"""Launcher for the clean bot package.

This replaces the old ``run-trading-bot.py`` which auto-installed pip packages
and shelled into ``final-trading-bot.py``. The legacy files are still in the
repo for reference.
"""

from bot.main import main

if __name__ == "__main__":
    raise SystemExit(main())
