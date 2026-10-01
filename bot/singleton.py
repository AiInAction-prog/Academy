"""Single-instance guard so only one live bot can run per account.

The bot places real (sim) orders; if two instances run against the same account
they double every position and the loss. This uses an OS advisory file lock
(``msvcrt`` on Windows, ``fcntl`` on POSIX) which the operating system releases
automatically when the holding process exits - so a crashed or orphaned process
never leaves a permanently stuck lock.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


class SingleInstanceError(RuntimeError):
    """Raised when another live instance already holds the lock."""


class SingleInstance:
    def __init__(self, key: str, lock_dir: str = "data") -> None:
        Path(lock_dir).mkdir(parents=True, exist_ok=True)
        self.path = Path(lock_dir) / f".bot_{key}.lock"
        self._fh = None  # type: ignore[assignment]

    def acquire(self) -> None:
        fh = open(self.path, "a+")
        try:
            if os.name == "nt":
                import msvcrt

                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            fh.close()
            raise SingleInstanceError(
                f"another instance holds {self.path}"
            ) from exc
        # We own the lock: record our pid for diagnostics.
        try:
            fh.seek(0)
            fh.truncate()
            fh.write(f"{os.getpid()}\n")
            fh.flush()
        except OSError:
            pass
        self._fh = fh

    def release(self) -> None:
        fh = self._fh
        if fh is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            fh.close()
        except OSError:
            pass
        self._fh = None

    def __enter__(self) -> "SingleInstance":
        self.acquire()
        return self

    def __exit__(self, *exc) -> None:
        self.release()
