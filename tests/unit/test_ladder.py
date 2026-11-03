"""FR-4.5 depth ladder: levels from the log, the window and threshold, never drops, key normalization."""

from __future__ import annotations

import pytest

from weaksquare.core.errors import ValidationError
from weaksquare.core.filters import FilterSpec, RatioBucket
from weaksquare.core.ladder import (
    LEVELS,
    ladder_key,
    status,
    validate_threshold,
    validate_window,
)

K = "k"


def test_a_new_ladder_starts_at_short() -> None:
    s = status(K, None, [], 80, 20)
    assert (s.level, s.step, s.played, s.wins, s.top) == (2, 1, 0, 0, False)


def test_moves_up_at_the_threshold_over_a_full_window() -> None:
    assert status(K, 2, [True] * 16 + [False] * 4, 80, 20).level == 3  # exactly 80%
    s = status(K, 2, [True] * 15 + [False] * 5, 80, 20)  # 75%
    assert (s.level, s.played, s.wins) == (2, 20, 15)


def test_needs_a_full_window_first() -> None:
    s = status(K, 2, [True] * 19, 80, 20)
    assert (s.level, s.played, s.wins) == (2, 19, 19)


def test_only_the_last_window_counts() -> None:
    old_misses = [False] * 30
    assert status(K, 3, old_misses + [True] * 20, 80, 20).level == 4
    assert status(K, 3, [True] * 30 + [False] * 5, 80, 20).level == 3  # 15/20 = 75%


def test_promotion_resets_the_window_and_stops_at_the_top() -> None:
    s = status(K, 3, [True] * 20, 80, 20)
    assert (s.level, s.played, s.wins, s.step) == (4, 0, 0, 3)
    top = status(K, 4, [True] * 20, 80, 20)
    assert (top.level, top.top, top.played) == (4, True, 20)


def test_never_drops() -> None:
    # The highest recorded level stands, however badly the window goes.
    s = status(K, 4, [False] * 20, 80, 20)
    assert s.level == 4


def test_settings_apply() -> None:
    assert status(K, 2, [True, True, False, True], 50, 4).level == 3
    assert status(K, 2, [True, True, False, True], 100, 4).level == 2


def test_key_ignores_order_and_irrelevant_match_mode() -> None:
    a = ladder_key(FilterSpec(themes=("pin", "fork")))
    assert a == ladder_key(FilterSpec(themes=("fork", "pin")))
    assert a != ladder_key(FilterSpec(themes=("fork", "pin"), match="all"))
    assert ladder_key(FilterSpec(themes=("fork",), match="all")) == ladder_key(FilterSpec(themes=("fork",)))
    assert ladder_key(FilterSpec()) != ladder_key(FilterSpec(exclude_themes=("mateIn1",)))
    # Filters other than the theme set don't start a new ladder.
    assert ladder_key(FilterSpec(rating_min=1500, side="black")) == ladder_key(FilterSpec())


def test_at_ladder_level_overrides_lengths_and_order() -> None:
    spec = FilterSpec(themes=("fork",), lengths=(1,), order="depth_ladder")
    level = spec.at_ladder_level(3)
    assert (level.lengths, level.order, level.themes) == ((3,), "random", ("fork",))
    assert LEVELS == (2, 3, 4)


def test_ladder_and_ratios_dont_combine() -> None:
    spec = FilterSpec(order="depth_ladder", ratios=(RatioBucket(("fork",), 50), RatioBucket(("pin",), 50)))
    with pytest.raises(ValidationError):
        spec.validate()
    FilterSpec(order="depth_ladder", themes=("fork",)).validate()


@pytest.mark.parametrize("bad", [9, 101, 80.0, True, "80", None])
def test_bad_threshold(bad: object) -> None:
    with pytest.raises(ValidationError):
        validate_threshold(bad)


@pytest.mark.parametrize("bad", [2, 101, 20.5, False, "20"])
def test_bad_window(bad: object) -> None:
    with pytest.raises(ValidationError):
        validate_window(bad)


def test_good_settings() -> None:
    assert validate_threshold(80) == 80 and validate_window(20) == 20 and validate_window(3) == 3
