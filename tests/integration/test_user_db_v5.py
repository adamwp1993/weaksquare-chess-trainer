"""user.db schema v5 (v0.6): Name-the-idea and Danger-spotting columns, and the mistake_reasons table."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

from weaksquare.adapters.db.migrate import load_migrations, migrate
from weaksquare.config import MIGRATIONS_DIR
from weaksquare.core.clock import FixedClock

USER = MIGRATIONS_DIR / "user"


def test_v4_attempts_keep_their_data_and_get_null_v06_columns(tmp_path: Path, clock: FixedClock) -> None:
    folder = tmp_path / "v4"
    folder.mkdir()
    for m in load_migrations(USER)[:4]:
        shutil.copy(m.path, folder / m.path.name)
    db = tmp_path / "user.db"
    migrate(db, folder, clock)
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO sessions (started_at, mode, filters_json) VALUES ('t', 'commit_line', '{}')")
    conn.execute(
        "INSERT INTO attempts (puzzle_source, puzzle_id, session_id, mode, started_at, finished_at, win,"
        " first_move_correct, line_correct, time_ms, sync_status, replies_correct, replies_total)"
        " VALUES ('lichess', 'OLD01', 1, 'commit_line', 't', 't', 0, 1, 0, 5, 'synced', 1, 2)"
    )
    conn.commit()
    conn.close()

    result = migrate(db, USER, clock, tmp_path / "backups")
    assert result.from_version == 4 and result.to_version >= 5  # later versions add migrations on top
    assert result.backup is not None  # NFR-3

    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT puzzle_id, replies_correct, replies_total, idea_tags, idea_found, idea_total, idea_extra,"
        " danger_candidate, danger_safe, danger_call FROM attempts"
    ).fetchone()
    assert row == ("OLD01", 1, 2, None, None, None, None, None, None, None)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(mistake_reasons)")]
    assert cols == ["id", "source", "ref_id", "reason", "suggested_reason", "note", "created_at"]
    assert conn.execute("SELECT COUNT(*) FROM mistake_reasons").fetchone() == (0,)
    indexes = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert "mistake_reasons_ref" in indexes
    conn.close()
