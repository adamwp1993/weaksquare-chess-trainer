from __future__ import annotations

import random

import pytest

from weaksquare.core.queue import (
    REFILL,
    allocate,
    draw_batch_size,
    order_by_theme,
    order_easy_to_hard,
    random_draws,
    refill_size,
    sample_random,
    theme_group,
)


def test_sample_is_deterministic_and_distinct() -> None:
    ids = list(range(1, 1001))
    a = sample_random(ids, 50, random.Random(7))
    b = sample_random(ids, 50, random.Random(7))
    assert a == b and len(set(a)) == 50
    assert a != sample_random(ids, 50, random.Random(8))


def test_sample_excludes_and_handles_small_pools() -> None:
    out = sample_random([1, 2, 3, 4], 10, random.Random(1), exclude={2})
    assert sorted(out) == [1, 3, 4]
    assert sample_random([], 5, random.Random(1)) == []


def test_random_draws_in_range() -> None:
    draws = random_draws(100, 1000, random.Random(3))
    assert min(draws) >= 1 and max(draws) <= 100


def test_refill_respects_fixed_queue_and_endless() -> None:
    assert refill_size(None, 500, 0) == REFILL
    assert refill_size(20, 0, 0) == 20
    assert refill_size(20, 18, 1) == 1
    assert refill_size(20, 20, 0) == 0
    assert refill_size(200, 0, 0) == REFILL


def test_draw_batch_size_scales_with_density() -> None:
    assert draw_batch_size(50, 1_000_000, 6_000_000) < draw_batch_size(50, 100_000, 6_000_000)
    assert draw_batch_size(50, 10, 6_000_000) == 5000


# ---- v0.2: ratios and order ---------------------------------------------------------------------


def test_allocate_ratio_over_1000_draws() -> None:
    """Done-when: a 50/30/20 ratio holds within ±5% over 1,000 draws (refills of 50, as a session does)."""
    rng = random.Random(3)
    weights, drawn = [50, 30, 20], [0, 0, 0]
    for _ in range(20):
        for b in allocate(weights, drawn, 50, rng):
            drawn[b] += 1
    assert sum(drawn) == 1000
    for got, w in zip(drawn, weights, strict=True):
        assert abs(got / 1000 * 100 - w) <= 5
    assert drawn == [500, 300, 200]  # quotas: exact, not just within 5%


@pytest.mark.parametrize("n", [1, 2, 3, 7, 15])
def test_allocate_short_sessions_within_one(n: int) -> None:
    slots = allocate([50, 30, 20], [0, 0, 0], n, random.Random(n))
    for b, w in enumerate([50, 30, 20]):
        assert abs(slots.count(b) - w * n / 100) < 1


def test_allocate_is_shuffled_and_deterministic() -> None:
    a = allocate([50, 50], [0, 0], 20, random.Random(1))
    assert a == allocate([50, 50], [0, 0], 20, random.Random(1))
    assert a != sorted(a)


def test_allocate_catches_up_a_bucket_that_fell_behind() -> None:
    # Bucket 0 is 10 behind its 50% share after an earlier refill came up short.
    slots = allocate([50, 50], [10, 30], 20, random.Random(2))
    assert slots.count(0) == 20


def test_order_easy_to_hard() -> None:
    assert order_easy_to_hard([3, 1, 2, 4], {1: 900, 2: 1500, 3: 1200, 4: 900}) == [1, 4, 3, 2]


def test_order_by_theme_follows_selection_order() -> None:
    keys = [1, 2, 3, 4, 5, 6]
    group = {1: "pin", 2: "fork", 3: "pin", 4: "skewer", 5: "fork", 6: "mate"}
    assert order_by_theme(keys, group, ["fork", "pin"]) == [2, 5, 1, 3, 4, 6]


def test_theme_group() -> None:
    assert theme_group(("middlegame", "pin", "fork"), ("fork", "pin")) == "fork"
    assert theme_group(("middlegame", "pin"), ()) == "middlegame"
    assert theme_group((), ("fork",)) == ""
