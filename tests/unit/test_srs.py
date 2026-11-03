"""FR-4.6 Leitner scheduling: box moves on win/loss, graduation, misses from any mode, calendar-day due."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from weaksquare.core.clock import FixedClock
from weaksquare.core.errors import ValidationError
from weaksquare.core.srs import (
    DEFAULT_INTERVALS,
    MODE,
    Card,
    Review,
    due_order,
    is_due,
    next_due,
    schedule,
    validate_intervals,
)

UTC_DATE = FixedClock().local_date
T0 = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)


def at(days: float) -> datetime:
    return T0 + timedelta(days=days)


def loss(days: float, mode: str = "standard") -> Review:
    return Review(at(days), mode, False)


def win(days: float, mode: str = MODE) -> Review:
    return Review(at(days), mode, True)


def card(*reviews: Review, intervals: tuple[int, ...] = DEFAULT_INTERVALS) -> Card | None:
    return schedule(reviews, intervals, UTC_DATE)


def test_never_missed_is_not_scheduled() -> None:
    assert card() is None
    assert card(win(0, "standard"), win(1, MODE)) is None  # an SRS win alone doesn't enter a box


def test_a_loss_in_any_mode_puts_it_in_box_one() -> None:
    for mode in ("standard", "commit_line", MODE):
        assert card(loss(0, mode)) == Card(1, date(2026, 11, 3))


def test_srs_wins_climb_the_boxes_using_each_interval() -> None:
    c = card(loss(0), win(1))
    assert c == Card(2, date(2026, 11, 3) + timedelta(days=3))
    c = card(loss(0), win(1), win(4), win(11))
    assert c == Card(4, date(2026, 11, 13) + timedelta(days=14))


def test_a_win_from_the_last_box_graduates() -> None:
    reviews = [loss(0)] + [win(d) for d in (1, 4, 11, 25)]
    assert card(*reviews) == Card(5, date(2026, 11, 27) + timedelta(days=30))
    graduated = card(*reviews, win(55))
    assert graduated is not None and graduated.graduated and graduated.due is None
    assert not is_due(graduated, date(2030, 1, 1))


def test_a_loss_resets_to_box_one_even_after_graduating() -> None:
    reviews = [loss(0)] + [win(d) for d in (1, 4, 11, 25, 55)]
    assert card(*reviews, loss(60, "commit_line")) == Card(1, date(2027, 1, 1) + timedelta(days=1))
    assert card(loss(0), win(1), win(4), loss(5)) == Card(1, date(2026, 11, 8))


def test_wins_outside_spaced_repetition_change_nothing() -> None:
    assert card(loss(0), win(1, "standard"), win(2, "commit_line")) == Card(1, date(2026, 11, 3))


def test_due_dates_are_local_calendar_days() -> None:
    # 22:30 UTC is 00:30 the next day in UTC+2: the miss falls on Nov 3 locally, so it is due Nov 4.
    tz = timezone(timedelta(hours=2))
    late = Review(datetime(2026, 11, 2, 22, 30, tzinfo=UTC), "standard", False)
    c = schedule([late], DEFAULT_INTERVALS, FixedClock(local_tz=tz).local_date)
    assert c == Card(1, date(2026, 11, 4))
    evening = Review(datetime(2026, 11, 2, 19, 0, tzinfo=UTC), "standard", False)  # 21:00 local
    c = schedule([evening], DEFAULT_INTERVALS, FixedClock(local_tz=tz).local_date)
    assert c is not None and c.due == date(2026, 11, 3)  # due next morning, not 24 h later
    assert is_due(c, date(2026, 11, 3)) and not is_due(c, date(2026, 11, 2))


def test_a_shrunk_intervals_setting_clamps_the_box() -> None:
    reviews = [loss(0), win(1), win(4), win(11)]  # box 4 with the defaults
    c = card(*reviews, intervals=(1, 2))
    assert c is not None and c.graduated  # box clamps to the last (2), and a win there graduates


def test_due_order_is_most_overdue_first_and_next_due() -> None:
    cards = {
        "A": Card(1, date(2026, 11, 3)),
        "B": Card(2, date(2026, 11, 1)),
        "C": Card(1, date(2026, 11, 1)),
        "D": Card(3, date(2026, 11, 9)),
        "E": Card(5, None, graduated=True),
    }
    assert due_order(cards, date(2026, 11, 3)) == ["C", "B", "A"]
    assert next_due(cards, date(2026, 11, 3)) == date(2026, 11, 9)
    assert next_due({"E": cards["E"]}, date(2026, 11, 3)) is None


@pytest.mark.parametrize(
    "value",
    [[1], list(range(1, 12)), [1, 1, 3], [3, 2], [0, 3], [1, 366], [1, 2.5], [True, 3], "1,3", None],
)
def test_bad_intervals_are_refused(value: object) -> None:
    with pytest.raises(ValidationError):
        validate_intervals(value)


def test_good_intervals() -> None:
    assert validate_intervals([1, 3, 7, 14, 30]) == DEFAULT_INTERVALS
    assert validate_intervals([2, 365]) == (2, 365)
