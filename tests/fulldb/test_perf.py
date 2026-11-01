"""Done-when: counts match direct SQL and return in < 500 ms on the full DB; a 50-puzzle queue
from a pool of at least 1M puzzles builds in < 500 ms. (`uv run pytest -m fulldb`)

Timings are taken after one warm-up query, i.e. with the database in the OS file cache, which is
how the app runs after its first count.
"""

from __future__ import annotations

import random
import sqlite3
import time

import pytest

from tests.integration.test_filter_count import oracle_count, random_specs
from weaksquare.core.filters import FilterSpec

pytestmark = pytest.mark.fulldb
LIMIT_S = 0.5
SEED = 7


@pytest.fixture(scope="module")
def raw(fulldb_path) -> sqlite3.Connection:  # type: ignore[no-untyped-def]
    conn = sqlite3.connect(f"file:{fulldb_path.as_posix()}?mode=ro", uri=True)
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def specs(raw: sqlite3.Connection) -> list[FilterSpec]:
    specs = random_specs(raw, 20, SEED)
    specs[0] = FilterSpec()  # the default: every puzzle
    specs[1] = FilterSpec(themes=("fork", "long"), match="all", rating_min=1200, rating_max=1600)
    return specs


@pytest.fixture(scope="module")
def warm(full_source) -> None:  # type: ignore[no-untyped-def]
    full_source.count(FilterSpec())


@pytest.mark.parametrize("i", range(20))
def test_count_under_500ms(full_source, specs, warm, i: int) -> None:  # type: ignore[no-untyped-def]
    started = time.perf_counter()
    full_source.count(specs[i])
    elapsed = time.perf_counter() - started
    assert elapsed < LIMIT_S, f"{elapsed * 1000:.0f} ms for {specs[i]}"


@pytest.mark.parametrize("i", range(20))
def test_count_matches_oracle_fulldb(full_source, specs, raw, i: int) -> None:  # type: ignore[no-untyped-def]
    assert full_source.count(specs[i]) == oracle_count(raw, specs[i])


def test_queue_50_from_1m_pool_under_500ms(full_source, warm, rng: random.Random) -> None:  # type: ignore[no-untyped-def]
    spec = FilterSpec(rating_min=1200, rating_max=2000)
    pool = full_source.count(spec)
    assert pool >= 1_000_000
    started = time.perf_counter()
    keys = full_source.sample_keys(spec, 50, rng, set(), pool)
    elapsed = time.perf_counter() - started
    assert len(keys) == len(set(keys)) == 50
    assert elapsed < LIMIT_S, f"{elapsed * 1000:.0f} ms"


def test_small_pool_queue_under_500ms(full_source, warm, rng: random.Random) -> None:  # type: ignore[no-untyped-def]
    spec = FilterSpec(themes=("fork", "long"), match="all", rating_min=1200, rating_max=1600)
    pool = full_source.count(spec)
    started = time.perf_counter()
    keys = full_source.sample_keys(spec, 50, rng, set(), pool)
    assert time.perf_counter() - started < LIMIT_S
    assert len(set(keys)) == 50
