"""user.db schema v7 (v0.8): games, account_sync, game_analysis, custom_puzzles and retry_attempts."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from weaksquare.adapters.db.migrate import load_migrations, migrate
from weaksquare.config import MIGRATIONS_DIR
from weaksquare.core.clock import FixedClock

USER = MIGRATIONS_DIR / "user"
NEW_TABLES = ("games", "account_sync", "game_analysis", "custom_puzzles", "retry_attempts")


def _v6_db(tmp_path: Path, clock: FixedClock) -> Path:
    folder = tmp_path / "v6"
    folder.mkdir()
    for m in load_migrations(USER)[:6]:
        shutil.copy(m.path, folder / m.path.name)
    db = tmp_path / "user.db"
    migrate(db, folder, clock)
    return db


def test_v6_database_gains_empty_game_tables_and_keeps_its_data(tmp_path: Path, clock: FixedClock) -> None:
    db = _v6_db(tmp_path, clock)
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO settings (key, value) VALUES ('ui.coordinates', 'false')")
    conn.commit()
    conn.close()

    result = migrate(db, USER, clock, tmp_path / "backups")
    assert result.from_version == 6 and result.to_version >= 7
    assert result.backup is not None  # NFR-3

    conn = sqlite3.connect(db)
    assert conn.execute("SELECT value FROM settings WHERE key = 'ui.coordinates'").fetchone() == ("false",)
    for t in NEW_TABLES:
        assert conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone() == (0,)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(game_analysis)")]
    assert cols[:2] == ["game_id", "ply"] and "multipv_json" in cols and "themes" in cols
    conn.close()


def _game(conn: sqlite3.Connection, source: str, gid: str | None, moves_hash: str = "h") -> int:
    cur = conn.execute(
        "INSERT INTO games (source, source_game_id, pgn, moves_hash, fetched_at) VALUES (?, ?, '1. e4 *', ?, 't')",
        (source, gid, moves_hash),
    )
    return int(cur.lastrowid or 0)


def test_a_platform_game_is_stored_once_but_pastes_without_an_id_are_not_constrained(
    tmp_path: Path, clock: FixedClock
) -> None:
    db = tmp_path / "user.db"
    migrate(db, USER, clock)
    conn = sqlite3.connect(db)
    _game(conn, "lichess", "GAMEID01")
    with pytest.raises(sqlite3.IntegrityError):
        _game(conn, "lichess", "GAMEID01")
    _game(conn, "chesscom", "GAMEID01")  # another platform's id space
    _game(conn, "paste", None)
    _game(conn, "paste", None)  # dedupe of pastes is by moves_hash, in the service
    conn.close()


def test_custom_puzzles_are_unique_per_game_ply_and_per_imported_set_entry(tmp_path: Path, clock: FixedClock) -> None:
    db = tmp_path / "user.db"
    migrate(db, USER, clock)
    conn = sqlite3.connect(db)
    gid = _game(conn, "lichess", "GAMEID02")
    ins = (
        "INSERT INTO custom_puzzles (game_id, ply, fen, solution_uci, length, player_color, origin, set_label,"
        " strict, created_at) VALUES (?, ?, 'F', ?, 1, 'white', ?, ?, ?, 't')"
    )
    conn.execute(ins, (gid, 10, "e2e4", "manual", None, 0))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(ins, (gid, 10, "d2d4", "manual", None, 0))
    conn.execute(ins, (None, None, "e2e4", "import", "Book", 1))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(ins, (None, None, "e2e4", "import", "Book", 1))
    conn.execute(ins, (None, None, "e2e4", "import", "Other book", 1))  # another set may hold the same puzzle
    conn.close()
