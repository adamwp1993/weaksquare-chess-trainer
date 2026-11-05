"""The journal's automatic daily log (v0.12, FR-10.68). Pure.

The puzzle part goes through `core/stats.build_report`, the function behind the Stats page, so the two can't
disagree: Danger spotting counts only under its mode and misclicks are left out (FR-4.4, FR-5.10).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from weaksquare.core.stats import DANGER, AttemptRow, Tally, build_report

TOP_MISSED = 3
SOURCE_LABELS = {"lichess": "Lichess puzzles", "my": "My puzzles"}


@dataclass(frozen=True)
class DayFacts:
    """What else happened that day, counted from stored rows."""

    games_synced: int = 0
    games_analyzed: int = 0
    games_reviewed: int = 0
    retries: int = 0
    retries_found: int = 0
    plan_tasks_done: int = 0
    coach_runs: tuple[str, ...] = ()  # each run's top weakness ("" when it had none)


@dataclass(frozen=True)
class DayLog:
    date: str
    overall: Tally
    by_mode: tuple[Tally, ...]
    by_source: tuple[Tally, ...]
    missed_themes: tuple[str, ...]  # display names, most missed first
    misclicks: int
    facts: DayFacts

    @property
    def empty(self) -> bool:
        f = self.facts
        return not (
            self.overall.attempts or self.by_mode or self.misclicks or f.games_synced or f.games_analyzed
            or f.games_reviewed or f.retries or f.plan_tasks_done or f.coach_runs
        )  # fmt: skip


def top_weakness(report: Mapping[str, Any]) -> str:
    """A report's top weakness, by score, for the log line."""
    best: Mapping[str, Any] | None = None
    for group in ("weaknesses", "whole_game"):
        for w in report.get(group) or ():
            if isinstance(w, Mapping) and (best is None or float(w.get("score") or 0) > float(best.get("score") or 0)):
                best = w
    return str(best.get("label") or best.get("key") or "") if best is not None else ""


def build_day(
    day: str, rows: Sequence[AttemptRow], sources: Sequence[str], theme_name: Callable[[str], str], facts: DayFacts
) -> DayLog:
    """One day's log. `sources[i]` is the puzzle source of `rows[i]`."""
    report = build_report(rows, theme_name)
    tallies: dict[str, list[AttemptRow]] = {}
    for r, s in zip(rows, sources, strict=True):
        if r.mode != DANGER and not r.misclick:  # as source_accuracy counts them (FR-9.7)
            tallies.setdefault(s, []).append(r)
    by_source = tuple(
        Tally(s, SOURCE_LABELS.get(s, s), len(v), sum(x.win for x in v), 0, 0) for s, v in sorted(tallies.items())
    )
    missed = sorted(
        (t for t in report.by_theme if t.attempts > t.solved),
        key=lambda t: (-(t.attempts - t.solved), t.label),
    )
    return DayLog(
        day, report.overall, tuple(report.by_mode), by_source, tuple(t.label for t in missed[:TOP_MISSED]),
        report.misclicks, facts,
    )  # fmt: skip
