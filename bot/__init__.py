"""Clean 2nd-trader runtime package.

Modules:
    config   - load .env + config/instruments.yaml into a typed Settings object
    broker   - TopstepX / ProjectX REST + SignalR client
    risk     - Topstep-style risk controls (daily loss, trailing DD, kill switch)
    logger   - structured per-day file logger
    main     - entry point wired up by run_bot.py
"""

__all__ = ["config", "broker", "risk", "logger", "main"]
