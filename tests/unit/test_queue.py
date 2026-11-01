from __future__ import annotations

import random

from weaksquare.core.queue import REFILL, draw_batch_size, random_draws, refill_size, sample_random


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
