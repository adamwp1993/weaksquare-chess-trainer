"""Queue building: random order (FR-3.11, random only in v0.1) and refills (FR-3.12). Pure; takes the rng.

Two sampling paths, both deterministic for a given rng state (plan decision 3):
- a small pool: the caller fetches every matching key, and `sample_random` picks from them;
- a large pool: `random_draws` proposes random keys in [1, max_key], and the caller keeps the ones
  that match the filters (rejection sampling), so a 1M-puzzle pool never has to be loaded.
"""

from __future__ import annotations

import random
from collections.abc import Collection, Sequence

SMALL_POOL = 100_000
REFILL = 50


def sample_random(candidates: Sequence[int], k: int, rng: random.Random, exclude: Collection[int] = ()) -> list[int]:
    """Up to `k` distinct candidates in random order, skipping `exclude`."""
    excluded = set(exclude)
    pool = [c for c in candidates if c not in excluded] if excluded else list(candidates)
    if k >= len(pool):
        rng.shuffle(pool)
        return pool
    return rng.sample(pool, k)


def random_draws(max_key: int, count: int, rng: random.Random) -> list[int]:
    """`count` random keys in [1, max_key] (with possible repeats; the caller de-duplicates)."""
    return [rng.randint(1, max_key) for _ in range(count)]


def draw_batch_size(needed: int, match_count: int, max_key: int) -> int:
    """How many keys to propose so that, at this match density, one batch usually suffices."""
    density = max(match_count / max(max_key, 1), 1e-6)
    return min(int(needed / density * 1.5) + 16, 5000)


def refill_size(queue_size: int | None, served: int, queued: int) -> int:
    """How many more puzzles to fetch: chunks of REFILL, never past a fixed queue size."""
    if queue_size is None:
        return REFILL
    return max(0, min(REFILL, queue_size - served - queued))
