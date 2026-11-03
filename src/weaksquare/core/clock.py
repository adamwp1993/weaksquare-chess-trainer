"""Injected time source (ARCHITECTURE §3 decision 15). core/ and services/ never read the clock directly."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, tzinfo
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...

    def monotonic_ms(self) -> int: ...

    def local_date(self, at: datetime) -> date:
        """The calendar day `at` falls on where the user is (Spaced repetition due dates, FR-4.6)."""
        ...


class FixedClock:
    """Deterministic clock for tests: starts at a fixed instant and only moves when told to."""

    def __init__(self, start: datetime | None = None, local_tz: tzinfo | None = None) -> None:
        self._now = start or datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        self._tz = local_tz or UTC

    def now(self) -> datetime:
        return self._now

    def monotonic_ms(self) -> int:
        return int(self._now.timestamp() * 1000)

    def local_date(self, at: datetime) -> date:
        return at.astimezone(self._tz).date()

    def advance(self, **kwargs: float) -> None:
        self._now += timedelta(**kwargs)
