"""The real clock and random source. Only app.py constructs these (ARCHITECTURE §3 decision 15)."""

from __future__ import annotations

import logging
import random
import secrets
import threading
import time
from datetime import UTC, date, datetime, timedelta


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic_ms(self) -> int:
        return time.monotonic_ns() // 1_000_000

    def local_date(self, at: datetime) -> date:
        return at.astimezone().date()  # the OS timezone


MAX_OFFSET_DAYS = 3650


class OffsetClock(SystemClock):
    """`--dev` runs only (FR-4.6 fast-forward time): the wall clock moved ahead by whole days, so
    Spaced-repetition misses come due without waiting. `monotonic_ms` (timings) is unaffected.
    app.py builds this only for the dev data folder; the real app uses SystemClock."""

    def __init__(self, days: int = 0) -> None:
        self._lock = threading.Lock()
        self._days = 0
        self.set_offset_days(days)

    @property
    def offset_days(self) -> int:
        with self._lock:
            return self._days

    def set_offset_days(self, days: int) -> None:
        if isinstance(days, bool) or not isinstance(days, int) or not 0 <= days <= MAX_OFFSET_DAYS:
            raise ValueError(f"the offset must be a whole number of days from 0 to {MAX_OFFSET_DAYS}")
        with self._lock:
            self._days = days

    def now(self) -> datetime:
        return super().now() + timedelta(days=self.offset_days)


def make_rng() -> random.Random:
    """One seeded Random for the whole app. The seed is logged so a session's queue can be replayed."""
    seed = secrets.randbits(64)
    logging.getLogger("weaksquare").info("random seed: %d", seed)
    return random.Random(seed)
