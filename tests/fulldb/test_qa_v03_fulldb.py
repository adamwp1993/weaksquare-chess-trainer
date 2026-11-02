"""QA v0.3 on the full DB: a heavy Lichess user (100,000 puzzles in the history) with the default
filters. The count stays exact and the sampler never serves a hidden puzzle. Written by the independent
QA pass (qa/QA-v0.3.md). Run: uv run pytest -m fulldb -s
"""

from __future__ import annotations

import random
import sqlite3
import time

import pytest

from weaksquare.core.filters import FilterSpec

pytestmark = pytest.mark.fulldb
HISTORY = 100_000


@pytest.fixture(scope="module")
def heavy(fulldb_path, tmp_path_factory):  # type: ignore[no-untyped-def]
    from weaksquare import config
    from weaksquare.adapters.db.connection import Database
    from weaksquare.adapters.db.migrate import migrate
    from weaksquare.adapters.db.repos.lichess import LichessHistoryRepo
    from weaksquare.adapters.db.repos.puzzles import LichessDbSource
    from weaksquare.core.clock import FixedClock

    user = tmp_path_factory.mktemp("qa-fulldb-v03") / "user.db"
    migrate(user, config.MIGRATIONS_DIR / "user", FixedClock())
    source = LichessDbSource(Database(user, fulldb_path))
    raw = sqlite3.connect(f"file:{fulldb_path.as_posix()}?mode=ro", uri=True)
    max_n = raw.execute("SELECT MAX(n) FROM puzzles").fetchone()[0]
    keys = random.Random(11).sample(range(1, max_n + 1), HISTORY)
    ids: list[str] = []
    for i in range(0, len(keys), 20_000):
        part = keys[i : i + 20_000]
        ids += [r[0] for r in raw.execute(f"SELECT id FROM puzzles WHERE n IN ({','.join(map(str, part))})")]
    LichessHistoryRepo(source._db).add([(pid, None, True) for pid in ids])
    yield source, raw, set(ids)
    raw.close()


def test_qa_default_count_with_100k_history(heavy) -> None:  # type: ignore[no-untyped-def]
    source, raw, played = heavy
    spec = FilterSpec()
    source.count(spec)
    t = time.perf_counter()
    got = source.count(spec)
    secs = time.perf_counter() - t
    print(f"\ndefault count with {len(played):,} history: {got:,} in {secs * 1000:.0f} ms")
    assert secs < 1.0  # NFR target for counts is ~0.5 s; report the number either way
    hidden = raw.execute(
        "SELECT COUNT(*) FROM puzzles WHERE popularity >= 50 AND nb_plays >= 100 AND n IN"
        " (SELECT n FROM puzzles WHERE id IN (SELECT value FROM json_each(?)))",
        (__import__("json").dumps(sorted(played)),),
    ).fetchone()[0]
    total = raw.execute("SELECT COUNT(*) FROM puzzles WHERE popularity >= 50 AND nb_plays >= 100").fetchone()[0]
    assert got == total - hidden


def test_qa_sampler_never_serves_a_played_puzzle(heavy) -> None:  # type: ignore[no-untyped-def]
    source, raw, played = heavy
    for spec in (FilterSpec(), FilterSpec(themes=("mateIn1",), rating_min=1400, rating_max=1450)):
        n = source.count(spec)
        keys = source.sample_keys(spec, 200, random.Random(3), set(), n)
        assert keys
        marks = ",".join(map(str, keys))
        got = {r[0] for r in raw.execute(f"SELECT id FROM puzzles WHERE n IN ({marks})")}
        assert not (got & played), sorted(got & played)[:5]
