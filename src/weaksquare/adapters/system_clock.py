"""The real clock and random source. Only app.py constructs these (ARCHITECTURE §3 decision 15)."""

from __future__ import annotations

import random
import secrets
import time
from datetime import UTC, datetime


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic_ms(self) -> int:
        return time.monotonic_ns() // 1_000_000


def make_rng() -> random.Random:
    """One seeded Random for the whole app. The seed is logged so a session can be replayed."""
    return random.Random(secrets.randbits(64))
