"""QA v0.1 extra checks on the full DB (`uv run pytest -m fulldb`).

- ALL / exclude across theme bits in different bitmask columns (t0, t1, t2) match the raw-text oracle.
- The rejection-sampling path is fast even at its sparsest (a pool just above the small-pool cut-off).
- Wide-open and heavily-excluded counts stay under 500 ms.
"""

from __future__ import annotations

import random
import sqlite3
import time

import pytest

from tests.integration.test_filter_count import oracle_count
from weaksquare.core.filters import FilterSpec
from weaksquare.core.queue import SMALL_POOL

pytestmark = pytest.mark.fulldb
LIMIT_S = 0.5


@pytest.fixture(scope="module")
def raw(fulldb_path) -> sqlite3.Connection:  # type: ignore[no-untyped-def]
    conn = sqlite3.connect(f"file:{fulldb_path.as_posix()}?mode=ro", uri=True)
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def bits(raw: sqlite3.Connection) -> dict[str, int]:
    return dict(raw.execute("SELECT theme, bit FROM theme_bits").fetchall())


def _by_column(bits: dict[str, int]) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    for t, b in sorted(bits.items(), key=lambda x: x[1]):
        out.setdefault(b // 62, []).append(t)
    return out


def test_all_and_exclude_across_bitmask_columns(full_source, raw, bits) -> None:  # type: ignore[no-untyped-def]
    cols = _by_column(bits)
    if len(cols) < 2:
        pytest.skip("every theme fits in one bitmask column")
    a, b = cols[0][0], cols[1][0]
    specs = [
        FilterSpec(themes=(a, b), match="all"),
        FilterSpec(themes=(a, b), match="any"),
        FilterSpec(themes=(a,), exclude_themes=(b,)),
        FilterSpec(exclude_themes=tuple(cols[1][:5]) + tuple(cols[0][:5])),
    ]
    for spec in specs:
        assert full_source.count(spec) == oracle_count(raw, spec), spec


def test_count_with_many_excludes_under_500ms(full_source, bits) -> None:  # type: ignore[no-untyped-def]
    full_source.count(FilterSpec())  # warm
    spec = FilterSpec(exclude_themes=tuple(sorted(bits))[:40])
    started = time.perf_counter()
    full_source.count(spec)
    assert time.perf_counter() - started < LIMIT_S


def test_sparse_rejection_sampling_under_500ms(full_source, raw) -> None:  # type: ignore[no-untyped-def]
    """The rejection path at its worst density: a pool just over SMALL_POOL out of ~6M puzzles."""
    full_source.count(FilterSpec())  # warm
    lo = raw.execute("SELECT MIN(rating) FROM puzzles").fetchone()[0]
    # Grow a rating band from the bottom until the pool just passes SMALL_POOL.
    hi = lo + 100
    pool = full_source.count(FilterSpec(rating_max=hi))
    while pool <= SMALL_POOL:
        hi += 25
        pool = full_source.count(FilterSpec(rating_max=hi))
    spec = FilterSpec(rating_max=hi)
    assert SMALL_POOL < pool < 3 * SMALL_POOL
    rng = random.Random(3)
    started = time.perf_counter()
    keys = full_source.sample_keys(spec, 50, rng, set(), pool)
    elapsed = time.perf_counter() - started
    assert len(set(keys)) == 50
    assert elapsed < LIMIT_S, f"{elapsed * 1000:.0f} ms for a pool of {pool:,}"
    # Every key really matches.
    placeholders = ",".join("?" * len(keys))
    bad = raw.execute(f"SELECT COUNT(*) FROM puzzles WHERE n IN ({placeholders}) AND rating > ?", (*keys, hi))
    assert bad.fetchone()[0] == 0
