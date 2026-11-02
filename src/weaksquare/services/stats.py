"""The Stats page (FR-9.1, FR-9.2, FR-9.4), read from the append-only attempts log (ARCHITECTURE §3 decision 4)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from weaksquare.core.stats import AttemptRow, Report, build_report
from weaksquare.core.themes import display_name


class AttemptSource(Protocol):
    def attempt_rows(self) -> list[AttemptRow]: ...


class RatingBackfill(Protocol):
    def backfill_puzzle_ratings(self) -> int: ...


class RatingSource(Protocol):
    def rating_points(self) -> list[Any]: ...

    def session_changes(self) -> list[Any]: ...


@dataclass(frozen=True)
class RatingHistory:
    points: list[Any] = field(default_factory=list)  # RatingPoint(at, rating, session_id)
    sessions: list[Any] = field(default_factory=list)  # SessionChange(session_id, started_at, change, solves)


class StatsService:
    def __init__(self, source: AttemptSource, backfill: RatingBackfill, ratings: RatingSource | None = None) -> None:
        self._source = source
        self._backfill = backfill
        self._ratings = ratings

    def report(self) -> Report:
        self._backfill.backfill_puzzle_ratings()  # attempts recorded before v0.2 (cheap once done)
        return build_report(self._source.attempt_rows(), display_name)

    def rating_history(self) -> RatingHistory:
        """FR-9.4: only ratings and changes Lichess returned with synced solves (FR-6.11d)."""
        if self._ratings is None:
            return RatingHistory()
        return RatingHistory(self._ratings.rating_points(), self._ratings.session_changes())
