"""v0.2 on the full DB: the new filters stay under 500 ms and match the oracle, with a realistic
history of 5,000 attempts; ratio and sorted queues build quickly; and the share of puzzles the default
quality filter removes is reported (Adam asked for it at planning). (`uv run pytest -m fulldb -s`)"""

from __future__ import annotations

import dataclasses
import random
import sqlite3
import time

import pytest

from tests.integration.test_filter_count import oracle_count
from weaksquare.core.filters import FilterSpec, RatioBucket
from weaksquare.services.session import SessionService

pytestmark = pytest.mark.fulldb
LIMIT_S = 0.5
OPEN = {"min_popularity": None, "min_plays": None, "exclude_solved_here": False}


@pytest.fixture(scope="module")
def raw(fulldb_path) -> sqlite3.Connection:  # type: ignore[no-untyped-def]
    conn = sqlite3.connect(f"file:{fulldb_path.as_posix()}?mode=ro", uri=True)
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def own_source(fulldb_path, tmp_path_factory):  # type: ignore[no-untyped-def]
    """Its own throwaway user.db: the attempts below must not leak into the other full-DB tests."""
    from weaksquare import config
    from weaksquare.adapters.db.connection import Database
    from weaksquare.adapters.db.migrate import migrate
    from weaksquare.adapters.db.repos.puzzles import LichessDbSource
    from weaksquare.core.clock import FixedClock

    user = tmp_path_factory.mktemp("fulldb-v02") / "user.db"
    migrate(user, config.MIGRATIONS_DIR / "user", FixedClock())
    return LichessDbSource(Database(user, fulldb_path))


@pytest.fixture(scope="module")
def history(own_source, raw: sqlite3.Connection) -> tuple[frozenset[str], frozenset[str]]:  # type: ignore[no-untyped-def]
    """5,000 attempts on 4,000 random puzzles in the throwaway user.db: (ever won, latest lost)."""
    rng = random.Random(5)
    max_n = raw.execute("SELECT MAX(n) FROM puzzles").fetchone()[0]
    keys = rng.sample(range(1, max_n + 1), 4000)
    ids = [r[0] for r in raw.execute(f"SELECT id FROM puzzles WHERE n IN ({','.join(map(str, keys))})")]
    results = {pid: [rng.random() < 0.7] for pid in ids}
    for pid in rng.sample(ids, 1000):
        results[pid].append(rng.random() < 0.5)
    with own_source._db.session() as conn:
        sid = conn.execute(
            "INSERT INTO sessions (started_at, mode, filters_json) VALUES ('t', 'standard', '{}')"
        ).lastrowid
        conn.executemany(
            "INSERT INTO attempts (puzzle_source, puzzle_id, session_id, mode, started_at, finished_at, win,"
            " first_move_correct, line_correct, time_ms) VALUES ('lichess', ?, ?, 'standard', 't', 't', ?, 0, 0, 1)",
            [(pid, sid, int(w)) for pid, ws in results.items() for w in ws],
        )
    solved = frozenset(p for p, ws in results.items() if any(ws))
    missed = frozenset(p for p, ws in results.items() if not ws[-1])
    own_source.count(FilterSpec())  # warm-up
    return solved, missed


def timed(fn):  # type: ignore[no-untyped-def]
    started = time.perf_counter()
    value = fn()
    return value, time.perf_counter() - started


def specs(raw: sqlite3.Connection) -> dict[str, FilterSpec]:
    family = raw.execute("SELECT tag FROM openings WHERE family_id IS NULL ORDER BY count DESC LIMIT 1").fetchone()[0]
    small = raw.execute("SELECT tag FROM openings WHERE family_id IS NOT NULL ORDER BY count LIMIT 1").fetchone()[0]
    return {
        "defaults (quality on, exclude solved)": FilterSpec(),
        "only my misses": FilterSpec(only_my_misses=True),
        "include solved, no quality": FilterSpec(**OPEN),  # type: ignore[arg-type]
        "strict quality, fork": FilterSpec(themes=("fork",), min_popularity=95, min_plays=5000),
        "biggest opening family": FilterSpec(openings=(family,)),
        "smallest variation": FilterSpec(openings=(small,)),
        "opening + theme + rating": FilterSpec(openings=(family,), themes=("pin",), rating_min=1500, rating_max=1900),
        "full rating range, all filters": FilterSpec(themes=("fork", "pin"), exclude_themes=("mate",), lengths=(2, 3),
                                                     side="white", min_popularity=80, min_plays=500),
    }  # fmt: skip


def test_v02_filters_fast_and_correct(own_source, raw, history) -> None:  # type: ignore[no-untyped-def]
    solved, missed = history
    slow = []
    for label, spec in specs(raw).items():
        count, elapsed = timed(lambda s=spec: own_source.count(s))
        assert count == oracle_count(raw, spec, solved, missed), label
        print(f"  {elapsed * 1000:6.0f} ms  {count:>9,}  {label}")
        if elapsed >= LIMIT_S:
            slow.append(f"{label}: {elapsed * 1000:.0f} ms")
    assert slow == []


def test_quality_default_share(own_source, raw, history) -> None:  # type: ignore[no-untyped-def]
    every = FilterSpec(**OPEN)  # type: ignore[arg-type]
    total = own_source.count(every)
    kept = own_source.count(dataclasses.replace(every, min_popularity=50, min_plays=100))
    pop = own_source.count(dataclasses.replace(every, min_popularity=50))
    plays = own_source.count(dataclasses.replace(every, min_plays=100))
    print(
        f"\n  quality defaults keep {kept:,} of {total:,} puzzles; they remove {total - kept:,} "
        f"({(total - kept) / total:.1%}). popularity < 50 alone: {total - pop:,} ({(total - pop) / total:.1%}); "
        f"fewer than 100 plays alone: {total - plays:,} ({(total - plays) / total:.1%})"
    )
    assert 0 < kept < total


class _Attempts:
    def append(self, *a, **k) -> int:  # type: ignore[no-untyped-def]
        return 0

    def session_tally(self, sid: int) -> object:
        return None

    def all_time_tally(self) -> object:
        return None


class _Sessions:
    n = 0

    def create(self, *a: object) -> int:
        self.n += 1
        return self.n


@pytest.mark.parametrize(
    "spec",
    [
        FilterSpec(ratios=(RatioBucket(("fork",), 50), RatioBucket(("pin", "skewer"), 30), RatioBucket(("oneMove",), 20)),
                   queue_size=None),
        FilterSpec(order="easy_to_hard", queue_size=500),
        FilterSpec(order="by_theme", themes=("fork", "pin", "skewer"), queue_size=500),
    ],
    ids=["ratio 50/30/20 endless", "easy to hard, 500", "by theme, 500"],
)  # fmt: skip
def test_v02_queues_build_quickly(own_source, history, spec: FilterSpec) -> None:  # type: ignore[no-untyped-def]
    from weaksquare.core.clock import FixedClock

    service = SessionService(own_source, _Attempts(), _Sessions(), FixedClock(), random.Random(3))  # type: ignore[arg-type]
    info, start_s = timed(lambda: service.start(spec))
    first, next_s = timed(lambda: service.next_puzzle(info.session_id))
    print(f"\n  start {start_s * 1000:.0f} ms, first puzzle {next_s * 1000:.0f} ms ({info.match_count:,} match)")
    assert first is not None and start_s + next_s < 2 * LIMIT_S
