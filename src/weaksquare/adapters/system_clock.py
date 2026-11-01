"""The real clock and random source. Only app.py constructs these (ARCHITECTURE §3 decision 15)."""

from __future__ import annotations

import logging
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
    """One seeded Random for the whole app. The seed is logged so a session's queue can be replayed."""
    seed = secrets.randbits(64)
    logging.getLogger("weaksquare").info("random seed: %d", seed)
    return random.Random(seed)
