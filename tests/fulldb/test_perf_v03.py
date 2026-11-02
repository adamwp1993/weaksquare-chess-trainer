"""v0.3 on the full DB: "exclude played on Lichess" (on by default) keeps the default count fast and
exact, with 20,000 puzzles in the Lichess history plus 5,000 attempts here. (`uv run pytest -m fulldb -s`)"""

from __future__ import annotations

import dataclasses
import random
import sqlite3
import time

import pytest

from weaksquare.core.filters import FilterSpec, RatioBucket

pytestmark = pytest.mark.fulldb
LIMIT_S = 0.5


@pytest.fixture(scope="module")
def setup(fulldb_path, tmp_path_factory):  # type: ignore[no-untyped-def]
    from weaksquare import config
    from weaksquare.adapters.db.connection import Database
    from weaksquare.adapters.db.migrate import migrate
    from weaksquare.adapters.db.repos.lichess import LichessHistoryRepo
    from weaksquare.adapters.db.repos.puzzles import LichessDbSource
    from weaksquare.core.clock import FixedClock

    user = tmp_path_factory.mktemp("fulldb-v03") / "user.db"
    migrate(user, config.MIGRATIONS_DIR / "user", FixedClock())
    source = LichessDbSource(Database(user, fulldb_path))
    raw = sqlite3.connect(f"file:{fulldb_path.as_posix()}?mode=ro", uri=True)
    rng = random.Random(7)
    max_n = raw.execute("SELECT MAX(n) FROM puzzles").fetchone()[0]
    keys = rng.sample(range(1, max_n + 1), 25_000)
    ids = [r[0] for r in raw.execute(f"SELECT id FROM puzzles WHERE n IN ({','.join(map(str, keys))})")]
    played, solved = ids[:20_000], ids[15_000:]  # 5,000 overlap: solved here and synced
    LichessHistoryRepo(source._db).add([(pid, None, True) for pid in played])
    with source._db.session() as conn:
        conn.execute("INSERT INTO sessions (started_at, mode, filters_json) VALUES ('t','standard','{}')")
        conn.executemany(
            "INSERT INTO attempts (puzzle_source, puzzle_id, session_id, mode, started_at, finished_at, win,"
            " first_move_correct, line_correct, time_ms) VALUES ('lichess', ?, 1, 'standard', 't', 't', 1, 1, 1, 1)",
            [(pid,) for pid in solved],
        )
    yield source, raw, set(played), set(solved)
    raw.close()


def _timed(fn):  # type: ignore[no-untyped-def]
    fn()  # warm
    t = time.perf_counter()
    out = fn()
    return out, time.perf_counter() - t


def test_default_count_with_lichess_history_is_fast_and_exact(setup) -> None:  # type: ignore[no-untyped-def]
    source, raw, played, solved = setup
    spec = FilterSpec()  # quality on, exclude solved on, exclude played on Lichess on
    got, secs = _timed(lambda: source.count(spec))
    print(f"\ndefault count with 20k Lichess history + 5k solved: {got:,} in {secs * 1000:.0f} ms")
    assert secs < LIMIT_S
    hidden = played | solved
    oracle_total = raw.execute("SELECT COUNT(*) FROM puzzles WHERE popularity >= 50 AND nb_plays >= 100").fetchone()[0]
    marks = ",".join("?" * len(hidden))
    hidden_match = raw.execute(
        f"SELECT COUNT(*) FROM puzzles WHERE popularity >= 50 AND nb_plays >= 100 AND id IN ({marks})", list(hidden)
    ).fetchone()[0]
    assert got == oracle_total - hidden_match


def test_ratio_count_with_history(setup) -> None:  # type: ignore[no-untyped-def]
    source, *_ = setup
    spec = FilterSpec(ratios=(RatioBucket(("fork",), 50), RatioBucket(("pin",), 30), RatioBucket(("mateIn1",), 20)),
                      rating_min=1200, rating_max=2000)  # fmt: skip
    (total, buckets), secs = _timed(lambda: source.count_with_buckets(spec))
    print(f"ratio count with history: {total:,} {buckets} in {secs * 1000:.0f} ms")
    assert secs < LIMIT_S
    off = dataclasses.replace(spec, exclude_played_on_lichess=False)
    assert source.count_with_buckets(off)[0] >= total
