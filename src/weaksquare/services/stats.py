"""The basic Stats page (FR-9.1, FR-9.2), read from the append-only attempts log (ARCHITECTURE §3 decision 4)."""

from __future__ import annotations

from typing import Protocol

from weaksquare.core.stats import AttemptRow, Report, build_report
from weaksquare.core.themes import display_name


class AttemptSource(Protocol):
    def attempt_rows(self) -> list[AttemptRow]: ...


class RatingBackfill(Protocol):
    def backfill_puzzle_ratings(self) -> int: ...


class StatsService:
    def __init__(self, source: AttemptSource, backfill: RatingBackfill) -> None:
        self._source = source
        self._backfill = backfill

    def report(self) -> Report:
        self._backfill.backfill_puzzle_ratings()  # attempts recorded before v0.2 (cheap once done)
        return build_report(self._source.attempt_rows(), display_name)
