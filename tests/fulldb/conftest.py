"""Opt-in tests against the full imported puzzle DB (`uv run pytest -m fulldb`).

The DB is opened read-only from the dev data folder (or --fulldb-path), with a throwaway user.db,
so these tests never write to any real data. They skip when no full DB is there.
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from weaksquare import config
from weaksquare.adapters.db.connection import Database
from weaksquare.adapters.db.migrate import migrate
from weaksquare.adapters.db.repos.puzzles import LichessDbSource
from weaksquare.core.clock import FixedClock

MIN_FULL = 1_000_000


@pytest.fixture(scope="session")
def fulldb_path(request: pytest.FixtureRequest) -> Path:
    given = request.config.getoption("--fulldb-path")
    path = Path(given) if given else config.default_data_dir(dev=True) / "puzzles.db"
    if not path.is_file():
        pytest.skip(f"no full puzzle DB at {path}: run uv run python scripts/fetch_puzzle_db.py --dev")
    return path


@pytest.fixture(scope="session")
def full_source(fulldb_path: Path, tmp_path_factory: pytest.TempPathFactory) -> LichessDbSource:
    user = tmp_path_factory.mktemp("fulldb") / "user.db"
    migrate(user, config.MIGRATIONS_DIR / "user", FixedClock())
    source = LichessDbSource(Database(user, fulldb_path))
    with source._db.session() as conn:
        n = conn.execute("SELECT COUNT(*) FROM pz.puzzles").fetchone()[0]
    if n < MIN_FULL:
        pytest.skip(f"{fulldb_path} has only {n:,} puzzles; this needs the full export")
    return source


@pytest.fixture
def rng() -> random.Random:
    return random.Random(99)
