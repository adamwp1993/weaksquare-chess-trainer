"""The puzzle source the session and the mixer see (v0.8, FR-3.15): Lichess DB, My puzzles, or both.

Keys stay plain ints: Lichess puzzles keep their positive `puzzles.n` keys, and your own puzzles use the
**negated** `custom_puzzles.id`, so one queue (and one "already served" set) holds both. Your own puzzles'
keys never change, so they survive a puzzle-DB re-import. Spaced repetition names them `my:<id>`
(`AttemptsRepo.srs_rows`). Ratios, the orders and the depth ladder are Lichess-only (FilterSpec rejects
them with My puzzles), so those calls go straight to the Lichess source.
"""

from __future__ import annotations

import random
from collections.abc import Sequence

from weaksquare.adapters.db.repos.custom_puzzles import CustomPuzzleSource
from weaksquare.adapters.db.repos.puzzles import LichessDbSource
from weaksquare.core.filters import FilterSpec
from weaksquare.core.puzzle import Puzzle

MY_PREFIX = "my:"


class CombinedSource:
    def __init__(self, lichess: LichessDbSource, mine: CustomPuzzleSource) -> None:
        self._lichess = lichess
        self._mine = mine

    def version(self) -> int:
        return self._lichess.version()

    def keys_for_ids(self, ids: list[str]) -> set[int]:
        return self._lichess.keys_for_ids([i for i in ids if not i.startswith(MY_PREFIX)])

    def counts(self, spec: FilterSpec) -> tuple[int, int]:
        """(Lichess, mine) for these filters."""
        lc = self._lichess.count(spec) if spec.source in ("lichess", "both") else 0
        mc = self._mine.count(spec) if spec.source in ("my", "both") else 0
        return lc, mc

    def count(self, spec: FilterSpec) -> int:
        return sum(self.counts(spec))

    def count_with_buckets(self, spec: FilterSpec) -> tuple[int, list[int]]:
        return self._lichess.count_with_buckets(spec)

    def theme_counts(self) -> dict[str, int]:
        return self._lichess.theme_counts()

    def openings(self) -> list[tuple[str, str | None, int]]:
        return self._lichess.openings()

    def _mine_keys(self, spec: FilterSpec, k: int, rng: random.Random, exclude: set[int]) -> list[int]:
        return [-i for i in self._mine.sample_keys(spec, k, rng, {-e for e in exclude if e < 0})]

    def sample_keys(
        self, spec: FilterSpec, k: int, rng: random.Random, exclude: set[int], match_count: int
    ) -> list[int]:
        if spec.source == "lichess":
            return self._lichess.sample_keys(spec, k, rng, exclude, match_count)
        if spec.source == "my":
            return self._mine_keys(spec, k, rng, exclude)
        # Both: each slot is yours with probability (your pool) / (both pools), so the mix follows the
        # pool sizes (plan v0.8). A pool that runs short leaves its slots to the other.
        lc, mc = self.counts(spec)
        if lc + mc == 0 or k <= 0:
            return []
        slots = [rng.random() < mc / (lc + mc) for _ in range(k)]
        mine = self._mine_keys(spec, sum(slots), rng, exclude)
        theirs = self._lichess.sample_keys(spec, k - sum(slots), rng, {e for e in exclude if e > 0}, lc)
        out: list[int] = []
        mi = ti = 0
        for is_mine in slots:
            if is_mine and mi < len(mine):
                out.append(mine[mi])
                mi += 1
            elif ti < len(theirs):
                out.append(theirs[ti])
                ti += 1
            elif mi < len(mine):
                out.append(mine[mi])
                mi += 1
        return out

    def get(self, key: int, version: int | None = None) -> Puzzle | None:
        if key < 0:
            return self._mine.get(-key)
        return self._lichess.get(key, version)

    def describe(self, keys: list[int]) -> dict[int, tuple[int, tuple[str, ...]]]:
        return self._lichess.describe([k for k in keys if k > 0])

    def has_puzzles(self, spec: FilterSpec) -> bool:
        return self._lichess.has_puzzles(spec)

    def levels_with_puzzles(self, spec: FilterSpec, levels: Sequence[int]) -> list[int]:
        return self._lichess.levels_with_puzzles(spec, levels)

    def count_level_and_above(self, spec: FilterSpec, level: int) -> tuple[int, int]:
        return self._lichess.count_level_and_above(spec, level)

    def key_map(self, ids: list[str]) -> dict[str, int]:
        """Spaced repetition: `my:<id>` maps to the negated id while the puzzle is active; Lichess IDs
        map to their current keys."""
        mine = {i: int(i[len(MY_PREFIX) :]) for i in ids if i.startswith(MY_PREFIX) and i[len(MY_PREFIX) :].isdigit()}
        active = self._mine.active(list(mine.values()))
        out = {i: -n for i, n in mine.items() if n in active}
        out.update(self._lichess.key_map([i for i in ids if not i.startswith(MY_PREFIX)]))
        return out
