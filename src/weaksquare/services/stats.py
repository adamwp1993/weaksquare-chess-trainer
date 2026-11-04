"""The Stats page (FR-9.1–9.4, 9.7), read from the append-only attempts log (ARCHITECTURE §3 decision 4)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from weaksquare.core.clock import Clock
from weaksquare.core.errors import ValidationError
from weaksquare.core.stats import MODE_LABELS, AttemptRow, ReasonReport, Report, build_report, reason_report
from weaksquare.core.themes import display_name, is_valid_key


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


@dataclass(frozen=True)
class GameStats:
    retry_found: int
    retry_tried: int
    sources: tuple[tuple[str, int, int], ...]  # (source, attempts, wins)


class StatsService:
    def __init__(
        self,
        source: AttemptSource,
        backfill: RatingBackfill,
        ratings: RatingSource | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._source = source
        self._backfill = backfill
        self._ratings = ratings
        self._clock = clock

    def report(self) -> Report:
        self._backfill.backfill_puzzle_ratings()  # attempts recorded before v0.2 (cheap once done)
        return build_report(self._source.attempt_rows(), display_name)

    def reasons(self, theme: Any = None, mode: Any = None, source: Any = "puzzles") -> ReasonReport:
        """FR-9.7: why you missed, for all of them or one theme and/or one mode. `source` (v0.8) is
        puzzles, games (your game mistakes and Retry misses) or all."""
        if theme is not None and not is_valid_key(theme):
            raise ValidationError("Not a theme key.")
        if mode is not None and mode not in MODE_LABELS:
            raise ValidationError("Unknown training mode.")
        if source not in ("puzzles", "games", "all"):
            raise ValidationError("source must be puzzles, games or all")
        local_date = self._clock.local_date if self._clock is not None else (lambda t: t.date())
        rows: list[AttemptRow] = []
        if source in ("puzzles", "all"):
            rows += self._source.attempt_rows()
        if source in ("games", "all") and hasattr(self._source, "game_reason_rows"):
            rows += self._source.game_reason_rows()
        return reason_report(rows, local_date, theme, mode)

    def game_stats(self) -> GameStats:
        """v0.8: Retry mode's found rate (FR-11.15) and local accuracy per puzzle source (FR-3.15)."""
        src: Any = self._source
        found, tried = src.retry_totals() if hasattr(src, "retry_totals") else (0, 0)
        per = src.source_accuracy() if hasattr(src, "source_accuracy") else []
        return GameStats(found, tried, tuple(per))

    def rating_history(self) -> RatingHistory:
        """FR-9.4: only ratings and changes Lichess returned with synced solves (FR-6.11d)."""
        if self._ratings is None:
            return RatingHistory()
        return RatingHistory(self._ratings.rating_points(), self._ratings.session_changes())
