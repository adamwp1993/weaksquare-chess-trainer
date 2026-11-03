"""Spaced repetition: the Leitner schedule (FR-4.6). Pure: the schedule is replayed from the attempts log.

- A loss in **any** mode puts the puzzle in box 1, due one interval later. Misses from before v0.5
  count too (Adam, v0.5 planning).
- A win **in Spaced-repetition mode** moves it up a box. A win from the last box graduates it: it's
  no longer scheduled. Wins in other modes change nothing.
- A later loss anywhere puts it back in box 1, even after it graduated.
- Due dates are local calendar days: a miss in the evening is due the next morning, not 24 hours later.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from weaksquare.core.errors import ValidationError

MODE = "spaced_repetition"
DEFAULT_INTERVALS: tuple[int, ...] = (1, 3, 7, 14, 30)  # days per box
MIN_BOXES, MAX_BOXES = 2, 10
MAX_INTERVAL_DAYS = 365


@dataclass(frozen=True)
class Review:
    """One recorded attempt of a puzzle, as the schedule sees it."""

    at: datetime  # finished_at
    mode: str
    win: bool


@dataclass(frozen=True)
class Card:
    box: int  # 1-based; meaningless once graduated
    due: date | None  # None once graduated
    graduated: bool = False


def validate_intervals(value: Any) -> tuple[int, ...]:
    """The box intervals setting: 2–10 boxes, whole days from 1 to 365, strictly increasing."""
    if not isinstance(value, list | tuple) or not MIN_BOXES <= len(value) <= MAX_BOXES:
        raise ValidationError(f"Spaced repetition needs {MIN_BOXES} to {MAX_BOXES} boxes.")
    days: list[int] = []
    for v in value:
        if isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= MAX_INTERVAL_DAYS:
            raise ValidationError(f"Each box is a whole number of days from 1 to {MAX_INTERVAL_DAYS}.")
        if days and v <= days[-1]:
            raise ValidationError("Each box must be longer than the one before it.")
        days.append(v)
    return tuple(days)


def schedule(
    reviews: Iterable[Review], intervals: Sequence[int], local_date: Callable[[datetime], date]
) -> Card | None:
    """Replay one puzzle's attempts (oldest first) into its card. None if it was never missed."""
    box: int | None = None
    due: date | None = None
    graduated = False
    last = len(intervals)
    for r in reviews:
        day = local_date(r.at)
        if not r.win:
            box, graduated = 1, False
            due = day + timedelta(days=intervals[0])
        elif box is not None and not graduated and r.mode == MODE:
            box = min(box, last)  # the intervals setting may have shrunk since
            if box == last:
                graduated, due = True, None
            else:
                box += 1
                due = day + timedelta(days=intervals[box - 1])
    if box is None:
        return None
    return Card(box, due, graduated)


def is_due(card: Card, today: date) -> bool:
    return not card.graduated and card.due is not None and card.due <= today


def due_order(cards: dict[str, Card], today: date) -> list[str]:
    """The puzzles due today, most overdue first (ties by lower box, then id, so it's deterministic)."""
    due = [(c.due, c.box, pid) for pid, c in cards.items() if is_due(c, today)]
    return [pid for _, _, pid in sorted(due)]  # type: ignore[type-var]


def next_due(cards: dict[str, Card], today: date) -> date | None:
    """The earliest date something comes due after today (for "next: Tue 4 Nov")."""
    upcoming = [c.due for c in cards.values() if not c.graduated and c.due is not None and c.due > today]
    return min(upcoming) if upcoming else None
