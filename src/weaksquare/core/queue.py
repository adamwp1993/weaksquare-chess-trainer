"""Queue building: sampling, ratios (FR-3.10), order (FR-3.11) and refills (FR-3.12). Pure; takes the rng.

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


# ---- ratios (FR-3.10) ------------------------------------------------------------------------
def allocate(weights: Sequence[int], drawn: Sequence[int], n: int, rng: random.Random) -> list[int]:
    """Which bucket each of the next `n` slots draws from, in random order.

    Quotas, not coin flips: after these slots, each bucket's total is its weight's share of all
    puzzles drawn so far (largest remainder, ties broken by the rng), so a 50/30/20 mix stays
    within one puzzle of exact even in a short session. `drawn` is what each bucket has given so far.
    """
    if n <= 0:
        return []
    total = sum(drawn) + n
    weight_sum = sum(weights)
    exact = [w * total / weight_sum for w in weights]
    target = [int(x) for x in exact]
    order = sorted(range(len(weights)), key=lambda i: (-(exact[i] - target[i]), rng.random()))
    for i in order[: total - sum(target)]:
        target[i] += 1
    # A bucket already ahead of its target (it made up for an exhausted one) gets nothing now.
    # sum(need) >= n always, because the targets add up to everything drawn plus n.
    need = [max(0, t - d) for t, d in zip(target, drawn, strict=True)]
    slots: list[int] = []
    while len(slots) < n:
        i = max(range(len(need)), key=lambda j: need[j])
        slots.append(i)
        need[i] -= 1
    rng.shuffle(slots)
    return slots


# ---- order (FR-3.11) -------------------------------------------------------------------------
def order_easy_to_hard(keys: Sequence[int], rating: dict[int, int]) -> list[int]:
    """Ascending rating; equal ratings keep their (random) order."""
    return sorted(keys, key=lambda k: rating.get(k, 0))


def order_by_theme(keys: Sequence[int], group: dict[int, str], group_order: Sequence[str]) -> list[int]:
    """All of one group, then the next. Groups follow `group_order` (the order you chose them in),
    then any others by first appearance; inside a group, keys keep their (random) order."""
    rank = {g: i for i, g in enumerate(group_order)}
    first_seen: dict[str, int] = {}
    for k in keys:
        first_seen.setdefault(group.get(k, ""), len(first_seen))
    return sorted(keys, key=lambda k: (rank.get(group.get(k, ""), len(rank)), first_seen[group.get(k, "")]))


def theme_group(themes: Sequence[str], selected: Sequence[str]) -> str:
    """The group a puzzle sorts into: the first selected theme it has, else its own first theme."""
    for t in selected:
        if t in themes:
            return t
    return themes[0] if themes else ""
