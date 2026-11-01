"""ARCHITECTURE §3 decision 12: one connection per thread; puzzles.db attached read-only."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from weaksquare.adapters.db.connection import Database
from weaksquare.adapters.db.migrate import migrate
from weaksquare.config import MIGRATIONS_DIR
from weaksquare.core.clock import FixedClock


@pytest.fixture
def db(tmp_path: Path, clock: FixedClock) -> Database:
    user, puzzles = tmp_path / "user.db", tmp_path / "puzzles.db"
    migrate(user, MIGRATIONS_DIR / "user", clock)
    migrate(puzzles, MIGRATIONS_DIR / "puzzles", clock)
    conn = sqlite3.connect(puzzles)
    conn.execute("INSERT INTO meta (key, value) VALUES ('row_count', '0')")
    conn.commit()
    conn.close()
    d = Database(user, puzzles)
    yield d
    d.close_all()


def test_each_thread_gets_its_own_connection(db: Database) -> None:
    ids: dict[str, int] = {}

    def grab(name: str) -> None:
        with db.session() as conn:
            ids[name] = id(conn)
            with db.session() as again:
                assert again is conn  # same thread, same connection

    threads = [threading.Thread(target=grab, args=(f"t{i}",)) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    grab("main")
    assert len(set(ids.values())) == 4


def test_wal_and_busy_timeout(db: Database) -> None:
    with db.session() as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000


def test_puzzles_attached_read_only(db: Database) -> None:
    assert db.puzzles_attached()
    with db.session() as conn:
        assert conn.execute("SELECT value FROM pz.meta WHERE key='row_count'").fetchone()[0] == "0"
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("INSERT INTO pz.meta (key, value) VALUES ('x', 'y')")


def test_works_without_puzzles_db(tmp_path: Path, clock: FixedClock) -> None:
    user = tmp_path / "user.db"
    migrate(user, MIGRATIONS_DIR / "user", clock)
    d = Database(user, tmp_path / "missing.db")
    assert not d.puzzles_attached()
    d.close_all()
